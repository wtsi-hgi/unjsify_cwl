# unjsify_cwl

Converts a CWL document with Inline Javascript expressions to a CWL document with steps that process those JavaScript expressions. This tool can be used for to convert CWL files to other workflow description formats which don't use JavaScript and also use different scripting languages in CWL, by providing a different expression evaluation driver.

## Example

```bash
$ unjsifycwl test/test_workflow.cwl -o test_out
$ cwltool test_out/test_workflow.cwl test/test_input.yaml
```

The script `nojscwltool` is included to test running a transpiled file against `cwltool` e.g. the above is equivalent to:

```bash
$ ./nojscwltool test/test_workflow.cwl test/test_input.yaml
```

## Conformance tests

To run the conformance tests, run the script `run_conformance_tests`. Note: not all of the confomance tests will pass, due to the reasons below.

## Limitations
- The runtime object is not passed into JavaScript expressions
- Schema salad interpolation is not correctly done - the file `cwl_model` needs to be used.
- Cannot generate CWL for which an step has the same input or output id as an existing id in a workflow, as input and output ids need to be generated.
- The nojscwltool file doesn't fully pass the conformance tests - this is due to a mixture of bugs in cwltool and bugs and limitations of this code.
