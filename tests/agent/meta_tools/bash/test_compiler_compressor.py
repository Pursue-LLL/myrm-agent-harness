from myrm_agent_harness.agent.meta_tools.bash.output_compressor import CompilerErrorCompressor


def test_compiler_error_compressor_tsc():
    compressor = CompilerErrorCompressor()

    # Mock tsc output with errors and code snippets
    tsc_output = (
        """
src/main.ts(10,5): error TS2322: Type 'string' is not assignable to type 'number'.
10     let x: number = "hello";
       ~
"""
        + "a" * 500
        + """
src/utils.ts(50,12): error TS2322: Type 'string' is not assignable to type 'number'.
50     return "world";
              ~~~~~~~
"""
        + "b" * 500
        + """
src/main.ts(15,1): error TS2532: Object is possibly 'undefined'.
15 obj.property = 1;
   ~~~
"""
        + "c" * 500
    )

    # It should only compress if is_failure=True
    assert compressor.compress(tsc_output, is_failure=False) is None

    compressed = compressor.compress(tsc_output, is_failure=True)

    assert compressed is not None
    assert "[System Note: Compiler output aggregated for clarity]" in compressed
    assert "src/main.ts:" in compressed
    assert "Line 10: [TS2322] Type 'string' is not assignable to type 'number'." in compressed
    assert "Line 15: [TS2532] Object is possibly 'undefined'." in compressed
    assert "src/utils.ts:" in compressed
    assert "Line 50: [TS2322] Type 'string' is not assignable to type 'number'." in compressed

    # Code snippets and squiggly lines should be removed
    assert "let x: number =" not in compressed
    assert "~~~~~~~" not in compressed

    # Summary should be present
    assert "Summary: Found 3 errors across 2 files. Top errors: TS2322 (2), TS2532 (1)." in compressed


def test_compiler_error_compressor_eslint():
    compressor = CompilerErrorCompressor()

    eslint_output = (
        """
/Users/user/project/src/main.ts
  10:5  error  'x' is assigned a value but never used  no-unused-vars
  15:1  error  Expected '===' and instead saw '=='     eqeqeq

/Users/user/project/src/utils.ts
  50:12  error  'y' is not defined                      no-undef

✖ 3 problems (3 errors, 0 warnings)
"""
        + "x" * 1000
    )

    compressed = compressor.compress(eslint_output, is_failure=True)

    assert compressed is not None
    assert "/Users/user/project/src/main.ts:" in compressed
    assert "Line 10: [no-unused-vars] 'x' is assigned a value but never used" in compressed
    assert "Line 15: [eqeqeq] Expected '===' and instead saw '=='" in compressed
    assert "/Users/user/project/src/utils.ts:" in compressed
    assert "Line 50: [no-undef] 'y' is not defined" in compressed

    assert "Summary: Found 3 errors across 2 files." in compressed


def test_compiler_error_compressor_truncates_many_errors():
    compressor = CompilerErrorCompressor()

    lines = []
    for i in range(30):
        lines.append(f"src/main.ts({i},1): error TS1000: Error {i}.")
        lines.append(f"{i} code snippet")

    tsc_output = "\n".join(lines)

    compressed = compressor.compress(tsc_output, is_failure=True)

    assert compressed is not None
    # Should only show 20 errors
    assert "Line 19: [TS1000] Error 19." in compressed
    assert "Line 20: [TS1000] Error 20." not in compressed

    assert "[System Note: Showing first 20 errors out of 30. Fix these and run again.]" in compressed
    assert "Summary: Found 30 errors across 1 files." in compressed
