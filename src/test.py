from context import truncate_tool_result


def test_truncate_tool_result():
    text = "x" * 10000
    out = truncate_tool_result(text)
    print(out)
    print(len(out))


def test_print():
    a = [1, 2, 3]
    print(a, sep=";;;")


if __name__ == "__main__":
    test_print()
