from unittest.mock import Mock, patch

import pytest

from patchwise.patch_review.patch_review import PatchReview
from patchwise.patch_review.static_analysis.coccicheck import Coccicheck


def make_coccicheck() -> Coccicheck:
    instance = object.__new__(Coccicheck)

    instance.logger = Mock()

    mock_commit = Mock()
    mock_commit.hexsha = "abc123"
    mock_commit.stats.files = {"drivers/test/file.c": {}}
    instance.commit = mock_commit

    mock_docker = Mock()
    mock_docker.sandbox_path = Path("/fake/sandbox")
    mock_docker.build_dir = "/fake/build"
    instance.docker_manager = mock_docker

    return instance

class TestSetup:
    def test_setup_does_not_create_symlink(self):
        """After the fix, setup() muts not call os.symlink at all."""
        instance = make_coccicheck()
        with patch(
            "patchwise.patch_review.static_analysis.coccicheck.os.symlink"
        ) as mock_symlink:
            instance.setup()
            mock_symlink.assert_not_called()

    def test_setup_does_not_set_symlink_path(self):
        """After the fix, setup() must not create a symlink_path attribute."""
        instance = make_coccicheck()
        instance.setup()
        assert not hasattr(instance, "symlink_path")

    def test_setup_satisfies_abstract_requirement(self):
        """setup() exists and is callable (satisfies PatchReview abstract method)."""
        instance = make_coccicheck()
        instance.setup()

class TestRunCoccicheck:
    @patch(
        "patchwise.patch_review.static_analysis.coccicheck.os.cpu_count",
        return_value=4,
    )
    def test_debug_file_is_dev_null(self, _mock_cpu_count):
        """
        _run_coccicheck must pass DEBUG_FILE=/dev/null directly.
        Without the fix, this would reference self.symlink_path and
        either use a stale host-side path or raise AttributeError.
        """
        instance = make_coccicheck()
        with patch.object(PatchReview, "run_cmd_with_timer", return_value="") as mock_run:
            instance._run_coccicheck("drivers/test")

        cmd = mock_run.call_args[0][0]
        assert "DEBUG_FILE=/dev/null" in cmd

    @patch(
        "patchwise.patch_review.static_analysis.coccicheck.os.cpu_count",
        return_value=4,
    )
    def test_no_symlink_path_reference_in_command(self, _mock_cpu_count):
        instance = make_coccicheck()
        assert not hasattr(instance, "symlink_path")

        with patch.object(PatchReview, "run_cmd_with_timer", return_value=""):
            instance._run_coccicheck("drivers/test")

    @patch(
        "patchwise.patch_review.static_analysis.coccicheck.os.cpu_count",
        return_value=4,
    )
    def test_command_contains_required_make_args(self, _mock_cpu_count):
        """_run_coccicheck passes the correct make targets and flags."""
        instance = make_coccicheck()
        with patch.object(PatchReview, "run_cmd_with_timer", return_value="") as mock_run:
            instance._run_coccicheck("drivers/test")

        cmd = mock_run.call_args[0][0]
        assert "coccicheck" in cmd
        assert "M=drivers/test" in cmd
        assert "MODE=report" in cmd
        assert "ARCH=arm64" in cmd
        assert "LLVM=1" in cmd

    @patch(
        "patchwise.patch_review.static_analysis.coccicheck.os.cpu_count",
        return_value=4,
    )
    def test_passes_correct_cwd(self, _mock_cpu_count):
        """_run_coccicheck uses docker_manager.build_dir as cwd."""
        instance = make_coccicheck()
        with patch.object(PatchReview, "run_cmd_with_timer", return_value="") as mock_run:
            instance._run_coccicheck("drivers/test")

        kwargs = mock_run.call_args[1]
        assert kwargs["cwd"] == "/fake/build"

class TestRunOrderingDependency:
    def test_run_does_not_require_setup(self):
        """
        run() must not raise AttributeError when setup() has never been called.

        Before the fix: run() -> _run_coccicheck() -> self.symlink_path raised
        AttributeError if setup() hadn't run first (the TODO).
        After the fix: symlink_path is never referenced so ordering is irrelevant.
        """
        instance = make_coccicheck()
        assert not hasattr(instance, "symlink_path")

        with patch.object(instance, "_prepare_kernel_build"), \
             patch.object(instance, "_run_coccicheck", return_value=""):
            instance.run() 

    def test_run_filters_output_to_modified_files_only(self):
        """
        run() includes only coccicheck lines that reference a modified file.

        Directory:  'drivers/test'  (dirname of the modified file)
        Coccicheck line: './file.c:10:1-5: WARNING: ...'
        -> strips './' -> 'file.c'
        -> joins with directory -> 'drivers/test/file.c'
        -> in modified_files -> included
        """
        instance = make_coccicheck()
        instance.commit.stats.files = {"drivers/test/file.c": {}}

        matching_line = "./file.c:10:1-5: WARNING: use of foo()"
        unrelated_line = "./other.c:5:1-3: WARNING: unrelated"

        coccicheck_output = f"{matching_line}\n{unrelated_line}\n"

        with patch.object(instance, "_prepare_kernel_build"), \
             patch.object(
                 instance, "_run_coccicheck", return_value=coccicheck_output
             ):
            result = instance.run()

        assert matching_line in result
        assert unrelated_line not in result

    def test_run_returns_empty_when_no_modified_files_match(self):
        """run() returns empty string when coccicheck output has no matches."""
        instance = make_coccicheck()
        instance.commit.stats.files = {"drivers/test/file.c": {}}

        with patch.object(instance, "_prepare_kernel_build"), \
             patch.object(
                 instance, "_run_coccicheck", return_value="./unrelated.c:1:1-2: WARNING: foo"
             ):
            result = instance.run()

        assert result == ""

    def test_run_returns_empty_on_no_coccicheck_output(self):
        """run() returns empty string when coccicheck produces no output."""
        instance = make_coccicheck()

        with patch.object(instance, "_prepare_kernel_build"), \
             patch.object(instance, "_run_coccicheck", return_value=""):
            result = instance.run()

        assert result == ""