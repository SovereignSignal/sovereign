# Release checks

Use an isolated test environment based on the Python version selected for the app build, with the existing archive-evidence dependency PyYAML available. The app runtime alone does not supply PyYAML; do not mistake that missing test dependency for a source regression. Record its version, the source commit, test output and exact bundle identity in the review packet. Run the full template suite and console backend/model suites before every packet. Re-run affected native fixture suites against the packaged candidate. All mutation tests use disposable archives and stubbed service controls.

```sh
export PATH="$SOV_TEST_PYTHON/bin:$PATH"
export PYTHONPATH="$PWD/lib"
python3 --version
python3 -c 'import yaml; print(yaml.__version__)'
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s apps/console/tests -p 'test_*.py' -v
for suite in apps/console/tests/*.cjs; do node "$suite" || exit; done
```

If a suite fails, compare against a clean main checkout with the same interpreter and environment. Keep baseline failures, new failures, environmental errors and skipped checks separate; a passing focused suite does not establish a passing full release. Resolve regressions before proposing deployment.

Independent review is optional, not a standing release gate. Do not engage Fable or another external reviewer unless the owner explicitly requests that reviewer for the current task. Approval to proceed with implementation or deployment does not authorize an external review. When requested, review the exact source commit, test evidence and built candidate, and record the scope and result. Approval of one slice does not approve unrelated changes. Obtain owner approval before installation, main publication or live cutover.

Deploy committed releases through Git. Preserve and hash any existing runtime changes, rehearse their reconciliation in disposable clones, retain a recoverable Git snapshot, then use a tested, owner-authorized fast-forward update. Do not copy release files over a live checkout and leave an uncommitted overlay. A source-branch backup is distinct from deploying that branch; each must stay within the owner's authorization.
