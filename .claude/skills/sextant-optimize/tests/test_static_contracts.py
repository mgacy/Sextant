import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
EXAMPLES = ROOT / "examples"
TEMPLATES = ROOT / "templates"


class SchemaError(AssertionError):
    pass


def load_json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def resolve_ref(schema, ref):
    if not ref.startswith("#/"):
        raise SchemaError(f"unsupported ref {ref}")
    node = schema
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def check_type(value, expected):
    expected_types = expected if isinstance(expected, list) else [expected]
    for type_name in expected_types:
        if type_name == "object" and isinstance(value, dict):
            return True
        if type_name == "array" and isinstance(value, list):
            return True
        if type_name == "string" and isinstance(value, str):
            return True
        if type_name == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if type_name == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if type_name == "boolean" and isinstance(value, bool):
            return True
        if type_name == "null" and value is None:
            return True
    return False


def validate(instance, schema_node, root_schema, path="$"):
    if "$ref" in schema_node:
        return validate(instance, resolve_ref(root_schema, schema_node["$ref"]), root_schema, path)

    if "const" in schema_node and instance != schema_node["const"]:
        raise SchemaError(f"{path}: expected const {schema_node['const']!r}, got {instance!r}")

    if "enum" in schema_node and instance not in schema_node["enum"]:
        raise SchemaError(f"{path}: {instance!r} not in enum")

    if "type" in schema_node and not check_type(instance, schema_node["type"]):
        raise SchemaError(f"{path}: expected type {schema_node['type']!r}, got {type(instance).__name__}")

    if isinstance(instance, dict):
        required = schema_node.get("required", [])
        for key in required:
            if key not in instance:
                raise SchemaError(f"{path}: missing required key {key}")
        properties = schema_node.get("properties", {})
        if schema_node.get("additionalProperties") is False:
            extra = set(instance) - set(properties)
            if extra:
                raise SchemaError(f"{path}: unexpected keys {sorted(extra)}")
        for key, value in instance.items():
            if key in properties:
                validate(value, properties[key], root_schema, f"{path}.{key}")

    if isinstance(instance, list):
        if "minItems" in schema_node and len(instance) < schema_node["minItems"]:
            raise SchemaError(f"{path}: expected at least {schema_node['minItems']} items")
        if "items" in schema_node:
            for index, item in enumerate(instance):
                validate(item, schema_node["items"], root_schema, f"{path}[{index}]")

    if isinstance(instance, str) and "minLength" in schema_node:
        if len(instance) < schema_node["minLength"]:
            raise SchemaError(f"{path}: expected non-empty string")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema_node and instance < schema_node["minimum"]:
            raise SchemaError(f"{path}: expected >= {schema_node['minimum']}")
        if "maximum" in schema_node and instance > schema_node["maximum"]:
            raise SchemaError(f"{path}: expected <= {schema_node['maximum']}")


class StaticContractTests(unittest.TestCase):
    def assert_valid(self, schema_name, example_name):
        schema = load_json(SCHEMAS / schema_name)
        example = load_json(EXAMPLES / example_name)
        validate(example, schema, schema)

    def test_run_config_template_matches_schema_and_uses_argv_commands(self):
        schema = load_json(SCHEMAS / "run-config.schema.json")
        template = load_json(TEMPLATES / "run-config.json")
        validate(template, schema, schema)

        command_paths = [
            ("tool", "versionCommand"),
            ("tool", "smokeTestCommand"),
            ("usage", "fetchCommand"),
            ("transcripts", "extractCommand"),
        ]
        for section, key in command_paths:
            command = template[section][key]
            self.assertIsInstance(command, list)
            self.assertTrue(command)
            self.assertTrue(all(isinstance(part, str) and part for part in command))

        self.assertFalse(template["scope"]["allowImplementation"])
        self.assertFalse(template["scope"]["allowDocsChanges"])
        self.assertEqual(template["scope"]["allowedArtifactRoot"], ".claude-tracking/tool-eval-runs")

    def test_optimization_state_example_matches_schema(self):
        self.assert_valid("optimization-state.schema.json", "optimization-state.json")

    def test_friction_events_example_matches_schema_and_allowed_values(self):
        self.assert_valid("friction-events.schema.json", "friction-events.json")
        event = load_json(EXAMPLES / "friction-events.json")["events"][0]
        self.assertEqual(event["category"], "fallbackSearch")
        self.assertEqual(event["suspectedFixLocus"], "sextant")
        self.assertTrue(event["verified"])
        self.assertTrue(event["evidence"])

    def test_scorecard_example_matches_schema_and_tracks_quality(self):
        self.assert_valid("scorecard.schema.json", "scorecard.json")
        scorecard = load_json(EXAMPLES / "scorecard.json")
        self.assertEqual(scorecard["tasks"][0]["answerQuality"], "grounded")
        self.assertIn("evaluationInvalid", scorecard["aggregate"])
        self.assertIn("highConfidenceOpportunities", scorecard["aggregate"])

    def test_opportunities_example_matches_schema(self):
        self.assert_valid("opportunities.schema.json", "opportunities.json")

    def test_task_corpus_example_matches_schema_and_approved_tasks(self):
        self.assert_valid("task-corpus.schema.json", "task-corpus.json")
        corpus = load_json(EXAMPLES / "task-corpus.json")
        self.assertEqual(
            [task["id"] for task in corpus["tasks"]],
            ["delegate-tracing-home-details", "child-reducer-integration"],
        )

    def test_role_artifact_examples_match_schemas(self):
        self.assert_valid("transcript-ref.schema.json", "transcript-ref.json")
        self.assert_valid("worker-completion.schema.json", "worker-completion.json")

    def test_prompt_templates_preserve_coordinator_boundaries(self):
        for path in TEMPLATES.glob("*.md"):
            text = path.read_text(encoding="utf-8")
            self.assertIn("Do not", text, path.name)
            self.assertIn("Output Contract", text, path.name)


if __name__ == "__main__":
    unittest.main()
