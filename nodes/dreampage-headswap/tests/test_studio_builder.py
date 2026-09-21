"""Workflow-installasjon skal avvise manglende valg uten aa kjoere modeller."""
import unittest

from scripts.build_klein_workflow import Graph


class StudioBuilderTests(unittest.TestCase):
    def graph(self, choice="klein9b"):
        schemas = {
            "Loader": {"input": {"required": {"model": (["klein9b"],)}},
                       "output": ["MODEL"]},
            "DP_Output": {"input": {"required": {"model": ("MODEL",)}},
                          "output": [], "output_node": True},
        }
        graph = Graph(schemas)
        graph.node("load", "Loader", "Model", (0, 0), (300, 100), {"model": choice})
        graph.node("output", "DP_Output", "Output", (400, 0), (300, 100))
        graph.link("load", 0, "output", "model")
        return graph

    def test_existing_model_and_connected_output(self):
        self.graph().validate()

    def test_missing_model_refused(self):
        with self.assertRaisesRegex(ValueError, "Unavailable selection"):
            self.graph("missing.safetensors").validate()

    def test_empty_inventory_refused(self):
        graph = self.graph()
        graph.schemas["Loader"]["input"]["required"]["model"] = ([],)
        with self.assertRaisesRegex(ValueError, "Unavailable selection"):
            graph.validate()

    def test_missing_required_wire_refused(self):
        graph = self.graph()
        graph.api["2"]["inputs"].clear()
        with self.assertRaisesRegex(ValueError, "Missing required inputs"):
            graph.validate()


if __name__ == "__main__":
    unittest.main()
