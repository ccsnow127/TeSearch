import pytest

from tesearch.data import DATA_ROOT, ModuleTask, count_public_callables, get_module, load_modules

needs_data = pytest.mark.skipif(not (DATA_ROOT / "test.parquet").exists(),
                                reason="run scripts/fetch_data.sh first")


def test_s_min_counts_public_functions_and_methods(task):
    assert count_public_callables(task.code_src) == 3   # add, sub, Box.get


def test_dotted_and_image(task):
    assert task.dotted == "flask.toy"
    assert task.image == "kdjain/swe-bench-pallets_flask-testbed:2.3"
    sk = ModuleTask(repo="scikit-learn/scikit-learn", version="0.20",
                    instance_id="scikit-learn__scikit-learn-10508", row_id="x", base_commit="",
                    patch="", code_file="sklearn/preprocessing/label.py", code_src="",
                    test_file="sklearn/preprocessing/tests/test_label.py")
    assert sk.image == "kdjain/swe-bench-scikit-learn_scikit-learn-instance:scikit-learn__scikit-learn-10508"
    assert sk.dotted == "sklearn.preprocessing.label"


@needs_data
def test_lite_split_has_129_modules():
    tasks = load_modules()
    assert len(tasks) == 129
    assert len({t.module_id for t in tasks}) == 129
    assert sum(len(t.instance_ids) for t in tasks) == 160
    for t in tasks:
        assert t.code_src and t.test_file and t.base_commit and t.s_min >= 1


@needs_data
def test_lookup_by_ids():
    t = get_module("django__django-17087")
    assert t.code_file == "django/db/migrations/serializer.py"
    assert t.instance_id == "django__django-17087"
    assert get_module(t.module_id).code_file == t.code_file
    assert get_module("_pytest.nodes").code_file == "src/_pytest/nodes.py"


@needs_data
def test_demo2_subset_resolves():
    from tesearch.data import load_subset
    tasks = load_subset("demo2")
    assert [t.code_file for t in tasks] == ["src/_pytest/mark/evaluate.py",
                                            "django/forms/boundfield.py"]
    assert all(t.instance_id in t.instance_ids for t in tasks)
