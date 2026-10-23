from models.train import load_model


def test_recommend_known_user():
    m = load_model()
    uid = next(iter(m.user_index))
    recs = m.recommend(uid, n=5)
    assert 0 < len(recs) <= 5
    assert all("item_id" in r for r in recs)


def test_unknown_user_falls_back_to_popular():
    assert len(load_model().recommend("does-not-exist", n=3)) == 3


def test_similar_items_excludes_self():
    m = load_model()
    iid = next(iter(m.item_index))
    assert iid not in [s["item_id"] for s in m.similar_items(iid, n=5)]
