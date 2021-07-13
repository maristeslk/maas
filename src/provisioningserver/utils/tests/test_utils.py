# -*- coding: utf-8 -*-

# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test `provisioningserver.utils`."""


from collections.abc import Iterator
from copy import deepcopy
import os
from unittest.mock import sentinel

from fixtures import EnvironmentVariableFixture
from testtools.matchers import DirExists, Equals, IsInstance

from maastesting.factory import factory
from maastesting.testcase import MAASTestCase
import provisioningserver
import provisioningserver.config
import provisioningserver.utils
from provisioningserver.utils import (
    CircularDependency,
    classify,
    convert_size_to_bytes,
    debian_to_kernel_architecture,
    flatten,
    is_instance_or_subclass,
    kernel_to_debian_architecture,
    locate_config,
    locate_template,
    Safe,
    ShellTemplate,
    sorttop,
    sudo,
    UnknownCapacityUnitError,
)


def get_run_path(*path):
    """Locate a file or directory relative to ``MAAS_ROOT``."""
    maas_root = os.environ["MAAS_ROOT"]
    return os.path.abspath(os.path.join(maas_root, *path))


class TestLocateConfig(MAASTestCase):
    """Tests for `locate_config`."""

    def test_returns_branch_etc_maas(self):
        self.assertEqual(get_run_path("etc/maas"), locate_config())
        self.assertThat(locate_config(), DirExists())

    def test_defaults_to_global_etc_maas_if_variable_is_unset(self):
        self.useFixture(EnvironmentVariableFixture("MAAS_ROOT", None))
        self.assertEqual("/etc/maas", locate_config())

    def test_defaults_to_global_etc_maas_if_variable_is_empty(self):
        self.useFixture(EnvironmentVariableFixture("MAAS_ROOT", ""))
        self.assertEqual("/etc/maas", locate_config())

    def test_returns_absolute_path(self):
        self.useFixture(EnvironmentVariableFixture("MAAS_ROOT", "."))
        self.assertTrue(os.path.isabs(locate_config()))

    def test_locates_config_file(self):
        filename = factory.make_string()
        self.assertEqual(
            get_run_path("etc/maas/", filename), locate_config(filename)
        )

    def test_locates_full_path(self):
        path = [factory.make_string() for counter in range(3)]
        self.assertEqual(
            get_run_path("etc/maas/", *path), locate_config(*path)
        )

    def test_normalizes_path(self):
        self.assertEqual(
            get_run_path("etc/maas/bar/szot"),
            locate_config("foo/.././bar///szot"),
        )


class TestLocateTemplate(MAASTestCase):
    """Tests for `locate_template`."""

    def test_returns_test_path(self):
        self.assertEquals(
            os.path.abspath(
                os.path.join(
                    os.path.dirname(__file__), "..", "..", "templates"
                )
            ),
            locate_template(""),
        )


class TestSafe(MAASTestCase):
    """Test `Safe`."""

    def test_value(self):
        something = object()
        safe = Safe(something)
        self.assertIs(something, safe.value)

    def test_repr(self):
        string = factory.make_string()
        safe = Safe(string)
        self.assertEqual("<Safe %r>" % string, repr(safe))


class TestShellTemplate(MAASTestCase):
    """Test `ShellTemplate`."""

    def test_substitute_escapes(self):
        # Substitutions are shell-escaped.
        template = ShellTemplate("{{a}}")
        expected = "'1 2 3'"
        observed = template.substitute(a="1 2 3")
        self.assertEqual(expected, observed)

    def test_substitute_does_not_escape_safe(self):
        # Substitutions will not be escaped if they're marked with `safe`.
        template = ShellTemplate("{{a|safe}}")
        expected = "$ ! ()"
        observed = template.substitute(a="$ ! ()")
        self.assertEqual(expected, observed)

    def test_substitute_does_not_escape_safe_objects(self):
        # Substitutions will not be escaped if they're `safe` objects.
        template = ShellTemplate("{{safe(a)}}")
        expected = "$ ! ()"
        observed = template.substitute(a="$ ! ()")
        self.assertEqual(expected, observed)


class TestClassify(MAASTestCase):
    def test_no_subjects(self):
        self.assertSequenceEqual(([], []), classify(sentinel.func, []))

    def test_subjects(self):
        subjects = [("one", 1), ("two", 2), ("three", 3)]

        def is_even(subject):
            return subject % 2 == 0

        self.assertSequenceEqual(
            (["two"], ["one", "three"]), classify(is_even, subjects)
        )


class TestFlatten(MAASTestCase):
    def test_returns_iterator(self):
        self.assertThat(flatten(()), IsInstance(Iterator))

    def test_returns_empty_when_nothing_provided(self):
        self.assertItemsEqual([], flatten([]))
        self.assertItemsEqual([], flatten(()))
        self.assertItemsEqual([], flatten({}))
        self.assertItemsEqual([], flatten(set()))
        self.assertItemsEqual([], flatten(([], (), {}, set())))
        self.assertItemsEqual([], flatten(([[]], ((),))))

    def test_flattens_list(self):
        self.assertItemsEqual([1, 2, 3, "abc"], flatten([1, 2, 3, "abc"]))

    def test_flattens_nested_lists(self):
        self.assertItemsEqual([1, 2, 3, "abc"], flatten([[[1, 2, 3, "abc"]]]))

    def test_flattens_arbitrarily_nested_lists(self):
        self.assertItemsEqual(
            [1, "two", "three", 4, 5, 6],
            flatten([[1], ["two", "three"], [4], [5, 6]]),
        )

    def test_flattens_other_iterables(self):
        self.assertItemsEqual(
            [1, 2, 3.3, 4, 5, 6], flatten([1, 2, {3.3, 4, (5, 6)}])
        )

    def test_treats_string_like_objects_as_leaves(self):
        # Strings are iterable, but we know they cannot be flattened further.
        self.assertItemsEqual(["abcdef"], flatten("abcdef"))

    def test_takes_star_args(self):
        self.assertItemsEqual("abcdef", flatten("a", "b", "c", "d", "e", "f"))


class TestSudo(MAASTestCase):
    def set_is_dev_environment(self, value):
        self.patch(provisioningserver.config, "is_dev_environment")
        provisioningserver.config.is_dev_environment.return_value = value

    def set_is_in_snap(self, value):
        self.patch(provisioningserver.utils.snappy, "running_in_snap")
        provisioningserver.utils.snappy.running_in_snap.return_value = value

    def test_returns_sudo_command_when_is_dev_environment(self):
        cmd = [factory.make_name("cmd") for _ in range(3)]
        self.set_is_dev_environment(True)
        self.set_is_in_snap(False)
        self.assertEqual(["sudo", "-n"] + cmd, sudo(cmd))

    def test_returns_same_command_when_in_snap(self):
        cmd = [factory.make_name("cmd") for _ in range(3)]
        self.set_is_dev_environment(False)
        self.set_is_in_snap(True)
        self.assertEqual(cmd, sudo(cmd))

    def test_returns_sudo_command_when_is_not_dev_environment(self):
        cmd = [factory.make_name("cmd") for _ in range(3)]
        self.set_is_dev_environment(False)
        self.set_is_in_snap(False)
        self.assertEqual(["sudo", "-n"] + cmd, sudo(cmd))


EMPTY = frozenset()


class TestSortTop(MAASTestCase):
    """Tests for `sorttop`."""

    def assertSort(self, data, *batches):
        self.assertThat(tuple(sorttop(data)), Equals(batches))

    def test_empty_yields_no_batches(self):
        self.assertSort({})

    def test_single_thing_without_dep_yields_single_batch(self):
        self.assertSort({7: EMPTY}, {7})

    def test_single_thing_referring_to_self_yields_single_batch(self):
        self.assertSort({7: {7}}, {7})

    def test_multiple_things_without_dep_yields_single_batch(self):
        self.assertSort({4: EMPTY, 5: EMPTY}, {4, 5})

    def test_multiple_things_with_deps_yields_multiple_batches(self):
        self.assertSort({1: {2}, 2: {3}, 3: EMPTY}, {3}, {2}, {1})

    def test_ghost_dependencies_appear_in_first_batch(self):
        # A "ghost" is a dependency that doesn't appear as a "thing", i.e. as
        # a key in the dict passed in to sorttop.
        self.assertSort({1: {2}, 3: EMPTY}, {2, 3}, {1})

    def test_circular_dependency_results_in_an_exception(self):
        self.assertRaises(CircularDependency, list, sorttop({1: {2}, 2: {1}}))

    def test_input_not_modified(self):
        data = {1: {2, 5}, 2: {3, 4, 5}, 6: {2}}
        orig = deepcopy(data)
        self.assertSort(data, {3, 4, 5}, {2}, {1, 6})
        self.assertThat(data, Equals(orig))

    def test_can_sort_non_numeric_things_too(self):
        computers = object()
        books = object()
        paper = object()
        silicon = object()
        data = {
            "alice": {"bob", "carol"},
            "bob": {"carol", "dave"},
            "carol": {computers, books},
            "dave": {books},
            books: {paper},
            computers: {books, silicon},
            True: {False},
        }
        self.assertSort(
            data,
            {silicon, paper, False},
            {books, True},
            {computers, "dave"},
            {"carol"},
            {"bob"},
            {"alice"},
        )


# Classes for testing `is_instance_or_type()`.
class Foo:
    pass


class Bar:
    pass


class Baz(Bar):
    pass


class TestIsInstanceOrSubclass(MAASTestCase):
    """Tests for `is_instance_or_subclass`."""

    scenarios = (
        ("instances", {"foo": Foo(), "bar": Bar(), "baz": Baz()}),
        ("types", {"foo": Foo, "bar": Bar, "baz": Baz}),
    )

    def test_accepts_correct_type(self):
        self.assertThat(is_instance_or_subclass(self.foo, Foo), Equals(True))
        self.assertThat(is_instance_or_subclass(self.bar, Bar), Equals(True))
        self.assertThat(is_instance_or_subclass(self.baz, Baz), Equals(True))

    def test_returns_false_if_object_is_not_relevant(self):
        self.assertThat(is_instance_or_subclass("Bar", Bar), Equals(False))

    def test_accept_subclass(self):
        self.assertThat(is_instance_or_subclass(self.baz, Bar), Equals(True))

    def test_rejects_incorrect_type(self):
        self.assertThat(is_instance_or_subclass(self.foo, Bar), Equals(False))
        self.assertThat(is_instance_or_subclass(self.bar, Baz), Equals(False))
        self.assertThat(is_instance_or_subclass(self.baz, Foo), Equals(False))

    def test_accepts_tuple_or_list(self):
        self.assertThat(
            is_instance_or_subclass(self.foo, (Baz, Foo, Bar)), Equals(True)
        )
        self.assertThat(
            is_instance_or_subclass(self.bar, (Baz, Foo)), Equals(False)
        )
        self.assertThat(
            is_instance_or_subclass(self.baz, [Bar, Foo]), Equals(True)
        )

    def test_accepts_variable_args(self):
        self.assertThat(
            is_instance_or_subclass(self.foo, Baz, Foo, Bar), Equals(True)
        )
        self.assertThat(
            is_instance_or_subclass(self.foo, Baz, Bar), Equals(False)
        )

    def test_accepts_non_flat_list(self):
        self.assertThat(
            is_instance_or_subclass(self.foo, (Baz, (Bar, (Foo,)))),
            Equals(True),
        )
        self.assertThat(
            is_instance_or_subclass(self.bar, *[Baz, [Bar, [Foo]]]),
            Equals(True),
        )


class TestConvertSizeToBytes(MAASTestCase):
    """Tests for `convert_size_to_bytes`."""

    scenarios = (
        ("bytes", {"value": "24111", "expected": 24111}),
        ("KiB", {"value": "2.21 KiB", "expected": int(2.21 * 2 ** 10)}),
        ("MiB", {"value": "2.21 MiB", "expected": int(2.21 * 2 ** 20)}),
        ("GiB", {"value": "2.21 GiB", "expected": int(2.21 * 2 ** 30)}),
        ("TiB", {"value": "2.21 TiB", "expected": int(2.21 * 2 ** 40)}),
        ("PiB", {"value": "2.21 PiB", "expected": int(2.21 * 2 ** 50)}),
        ("EiB", {"value": "2.21 EiB", "expected": int(2.21 * 2 ** 60)}),
        ("ZiB", {"value": "2.21 ZiB", "expected": int(2.21 * 2 ** 70)}),
        ("YiB", {"value": "2.21 YiB", "expected": int(2.21 * 2 ** 80)}),
        (
            "whitespace",
            {"value": "2.21   GiB", "expected": int(2.21 * 2 ** 30)},
        ),
        ("zero", {"value": "0 TiB", "expected": 0}),
    )

    def test_convert_size_to_bytes(self):
        self.assertEqual(self.expected, convert_size_to_bytes(self.value))


class TestConvertSizeToBytesErrors(MAASTestCase):
    """Error handling tests for `convert_size_to_bytes`."""

    def test_unknown_capacity_unit(self):
        error = self.assertRaises(
            UnknownCapacityUnitError, convert_size_to_bytes, "200 superbytes"
        )
        self.assertEqual("Unknown capacity unit 'superbytes'", str(error))

    def test_empty_string(self):
        self.assertRaises(ValueError, convert_size_to_bytes, "")

    def test_empty_value(self):
        self.assertRaises(ValueError, convert_size_to_bytes, " KiB")


class TestKernelToDebianArchitecture(MAASTestCase):
    """Tests for `kernel_to_debian_architecture`."""

    scenarios = (
        ("i386", {"kernel": "i686", "debian": "i386/generic"}),
        ("x86_64", {"kernel": "x86_64", "debian": "amd64/generic"}),
        ("aarch64", {"kernel": "aarch64", "debian": "arm64/generic"}),
        ("ppc64le", {"kernel": "ppc64le", "debian": "ppc64el/generic"}),
        ("s390x", {"kernel": "s390x", "debian": "s390x/generic"}),
        ("mips", {"kernel": "mips", "debian": "mips/generic"}),
        ("mips64", {"kernel": "mips64", "debian": "mips64el/generic"}),
    )

    def test_kernel_to_debian_architecture(self):
        self.assertEquals(
            self.debian, kernel_to_debian_architecture(self.kernel)
        )


class TestDebianToKernalArchitecture(MAASTestCase):
    """Tests for `debian_to_kernal_architecture`."""

    scenarios = (
        ("i386/generic", {"kernel": "i686", "debian": "i386/generic"}),
        ("amd64/generic", {"kernel": "x86_64", "debian": "amd64/generic"}),
        ("arm64/generic", {"kernel": "aarch64", "debian": "arm64/generic"}),
        (
            "ppc64el/generic",
            {"kernel": "ppc64le", "debian": "ppc64el/generic"},
        ),
        ("s390x/generic", {"kernel": "s390x", "debian": "s390x/generic"}),
        ("mips/generic", {"kernel": "mips", "debian": "mips/generic"}),
        (
            "mips64el/generic",
            {"kernel": "mips64", "debian": "mips64el/generic"},
        ),
    )

    def test_kernel_to_debian_architecture(self):
        self.assertEquals(
            self.kernel, debian_to_kernel_architecture(self.debian)
        )
