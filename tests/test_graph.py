import networkx as nx

from src.graph.build import affiliation_graph, build_graph, node, shortest_path_to


def test_graph_from_db(db):
    g = build_graph(db)
    counts = {k: sum(1 for _, d in g.nodes(data=True) if d["kind"] == k)
              for k in ("employee", "person", "organization", "group")}
    assert counts == {"employee": 150, "person": db.execute("SELECT count(*) FROM persons").fetchone()[0],
                      "organization": 300, "group": 26}
    n_rel = db.execute("SELECT count(*) FROM relations").fetchone()[0]
    n_roles = db.execute("SELECT count(*) FROM org_roles").fetchone()[0]
    n_members = db.execute("SELECT count(*) FROM group_members").fetchone()[0]
    assert g.number_of_edges() == n_rel + n_roles + n_members


def test_affiliation_graph_keeps_only_allowed_types(db):
    gaff = affiliation_graph(build_graph(db))
    assert {d["rel"] for _, _, d in gaff.edges(data=True)} <= {"RELATIVE", "EX_EMPLOYER", "SAME_PROJECT"}


def test_shortest_path_deterministic():
    g = nx.Graph()
    g.add_edge("employee:1", "person:5")
    g.add_edge("person:5", "person:9")
    g.add_edge("employee:2", "person:9")
    g.add_edge("employee:3", "x:1")
    g.add_edge("x:1", "x:2")
    g.add_edge("x:2", "person:7")
    assert shortest_path_to(g, ["employee:1", "employee:2"], {"person:9"}, 2) == ["employee:2", "person:9"]
    assert shortest_path_to(g, ["employee:1"], {"person:9"}, 1) is None
    assert shortest_path_to(g, ["employee:3"], {"person:7"}, 2) is None   # путь длины 3
    assert node("employee", 4) == "employee:4"
