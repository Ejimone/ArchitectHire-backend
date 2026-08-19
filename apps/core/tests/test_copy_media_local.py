"""Copying media out of object storage onto the VM's disk.

The command runs while the site is still serving from the bucket, so its contract is
narrow and worth pinning down: it must be safe to run twice, it must never leave a
truncated file behind, and one missing object must not abandon the migration half-done.
"""

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command

from apps.cms.models import CaseCard


@pytest.mark.django_db
class TestCopyMediaLocal:
    def _card(self, title="Copy probe", data=b"a photograph"):
        card = CaseCard.objects.create(scope="landing", title=title)
        card.image.save("copy-probe.webp", ContentFile(data), save=True)
        return card

    def test_it_copies_a_referenced_file_under_the_same_name(self, tmp_path, capsys):
        card = self._card()

        call_command("copy_media_local", dest=str(tmp_path))

        target = tmp_path / card.image.name
        # The name is what the database stores; the copy has to land under it byte for
        # byte or the flip to MEDIA_BACKEND=local 404s every image on the site.
        assert target.read_bytes() == b"a photograph"
        assert str(tmp_path) in capsys.readouterr().out

    def test_a_second_run_copies_nothing(self, tmp_path, capsys):
        self._card()
        call_command("copy_media_local", dest=str(tmp_path))
        capsys.readouterr()

        call_command("copy_media_local", dest=str(tmp_path))

        assert "copied 0, already present" in capsys.readouterr().out

    def test_a_file_of_the_wrong_size_is_copied_again(self, tmp_path):
        card = self._card()
        target = tmp_path / card.image.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"truncated")  # an interrupted earlier run

        call_command("copy_media_local", dest=str(tmp_path))

        assert target.read_bytes() == b"a photograph"

    def test_dry_run_writes_nothing(self, tmp_path, capsys):
        card = self._card()

        call_command("copy_media_local", dest=str(tmp_path), dry_run=True)

        assert not (tmp_path / card.image.name).exists()
        assert "would copy" in capsys.readouterr().out

    def test_an_object_missing_from_storage_is_named_and_skipped(self, tmp_path, capsys):
        card = self._card()
        other = self._card(title="Second probe", data=b"another photograph")
        card.image.storage.delete(card.image.name)

        call_command("copy_media_local", dest=str(tmp_path))

        out = capsys.readouterr()
        assert f"missing: {card.image.name}" in out.err
        assert not (tmp_path / card.image.name).exists()
        # The healthy row still made it: one broken reference is a pre-existing problem,
        # not a reason to leave the migration half-done.
        assert (tmp_path / other.image.name).read_bytes() == b"another photograph"

    def test_private_files_land_outside_the_public_root(self, tmp_path, django_user_model):
        """A credential scan must never end up under a root Caddy serves as static files."""
        from apps.providers.models import Credential

        user = django_user_model.objects.create_user(email="copy-probe@example.com", password="x")
        credential = Credential.objects.create(user=user, kind=Credential.Kind.PE_LICENSE)
        credential.document.save("licence.pdf", ContentFile(b"private bytes"), save=True)

        call_command(
            "copy_media_local",
            dest=str(tmp_path / "public"),
            private_dest=str(tmp_path / "private"),
        )

        assert (tmp_path / "private" / credential.document.name).read_bytes() == b"private bytes"
        assert not (tmp_path / "public" / credential.document.name).exists()

    def test_the_private_root_defaults_beside_the_public_one(self, tmp_path, capsys, settings):
        del settings.PRIVATE_MEDIA_ROOT
        self._card()

        call_command("copy_media_local", dest=str(tmp_path / "media"))

        assert str(tmp_path / "media-private") in capsys.readouterr().out
