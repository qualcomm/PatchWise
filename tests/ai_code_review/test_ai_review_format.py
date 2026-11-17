# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Tests for formatting prose without damaging code in AI responses."""

import types

from patchwise.patch_review.ai_review.ai_review import AiReview


class _ConcreteAiReview(AiReview):
    def run(self):
        raise NotImplementedError


def _review() -> AiReview:
    review = _ConcreteAiReview.__new__(_ConcreteAiReview)
    review.docker_manager = types.SimpleNamespace(container_name="__test_shell__")
    return review


def test_format_chat_response_wraps_long_prose():
    text = (
        "This is a long explanatory paragraph returned by the reviewer and it "
        "must be wrapped so that the resulting email remains readable in clients "
        "that expect a traditional seventy-five column message."
    )

    result = _review().format_chat_response(text)

    assert result != text
    assert all(len(line) <= 75 for line in result.splitlines())
    assert result.replace("\n", " ") == text


def test_format_chat_response_preserves_fenced_code_and_wraps_surrounding_prose():
    code = (
        "```c\n"
        "static int function_with_a_name_longer_than_seventy_five_columns(void)\n"
        "{\n"
        "\treturn 0;\n"
        "}\n"
        "```"
    )
    text = (
        "This introductory explanation is deliberately long enough to require "
        "wrapping before the example.\n"
        f"{code}\n"
        "This concluding explanation is also deliberately long enough to require "
        "wrapping after the example."
    )

    result = _review().format_chat_response(text)

    assert code in result
    before, after = result.split(code)
    assert max(map(len, before.splitlines())) <= 75
    assert max(map(len, after.splitlines())) <= 75


def test_format_chat_response_preserves_unclosed_fenced_block():
    prefix = (
        "A sufficiently long introduction should be wrapped before the unfinished "
        "code block starts in this response."
    )
    unfinished = (
        "```c\n"
        "static int function_with_a_name_longer_than_seventy_five_columns(void)\n"
        "{\n"
        "\treturn -EINVAL;\n"
        "}"
    )

    result = _review().format_chat_response(f"{prefix}\n{unfinished}")

    assert result.endswith(unfinished)
    assert result != f"{prefix}\n{unfinished}"


def test_format_chat_response_preserves_unfenced_multiline_c_code():
    code = (
        "static int function_with_a_name_longer_than_seventy_five_columns(void)\n"
        "{\n"
        "return -EINVAL;\n"
        "}"
    )

    assert _review().format_chat_response(code) == code


def test_format_chat_response_does_not_mistake_c_discussion_for_code():
    text = (
        "The static function returns an integer when validation fails and callers "
        "must handle that value instead of continuing with an invalid object.\n"
        "This explanation mentions C vocabulary but remains ordinary prose that "
        "should be reflowed for the email response."
    )

    result = _review().format_chat_response(text)

    assert result != text
    assert all(len(line) <= 75 for line in result.splitlines())


def test_format_chat_response_does_not_classify_single_line_c_as_code():
    code = (
        "static int function_with_a_name_longer_than_seventy_five_columns_and_then_some(void);"
    )

    result = _review().format_chat_response(code)

    assert result != code
    assert all(len(line) <= 75 for line in result.splitlines())


def test_format_chat_response_preserves_indented_text():
    text = "    " + "an intentionally indented line " * 4

    assert len(text) > 75
    assert _review().format_chat_response(text) == text
