"""Small deterministic feature-recipe catalog for unfamiliar CAD requests.

Recipes are graph patterns, not finished models.  The planner fills dimensions
from the user's prompt and the validator still decides whether the resulting
IR is executable.  Keeping them data-only makes them safe to include in an
LLM prompt and easy to grow from successful Agent trajectories.
"""
from __future__ import annotations

import math
import re
from typing import Any


FEATURE_RECIPES: tuple[dict[str, Any], ...] = (
    {
        "id": "mounting_hole_pattern",
        "keywords": ("hole", "holes", "bore", "flange", "bolt", "mounting", "fastener", "孔", "法兰"),
        "intent": "drill repeated through holes around a body",
        "graph": [
            "body (existing solid)",
            "cylinder cutter at the first pitch-circle position",
            "polar_pattern(cutter, count, axis=[0,0,1])",
            "cut(body, patterned cutters)",
        ],
        "checks": ["hole count", "hole diameter", "pitch radius", "single solid"],
    },
    {
        "id": "linear_fins",
        "keywords": ("fin", "finned", "heat sink", "rib", "web", "鳍片", "散热", "加强筋"),
        "intent": "repeat a thin fin across the top of a base plate",
        "graph": [
            "base box",
            "one fin box touching the top face of the base",
            "linear_pattern(fin, count, spacing=[pitch,0,0])",
            "union(base, patterned fins)",
        ],
        "checks": ["fin count", "fin pitch", "fin thickness", "base contact"],
    },
    {
        "id": "stepped_shaft",
        "keywords": ("shaft", "stepped", "axle", "阶梯轴", "传动轴"),
        "intent": "stack coaxial cylindrical stages along one axis",
        "graph": [
            "cylinder stage 1 at z=0",
            "translate stage 2 by stage_1_length",
            "translate stage 3 by stage_1_length + stage_2_length",
            "union(all stages)",
        ],
        "checks": ["coaxiality", "stage lengths", "non-zero overlap/contact", "single solid"],
    },
    {
        "id": "dovetail_base",
        "keywords": ("dovetail", "燕尾", "slide", "rail", "导轨"),
        "intent": "extrude a trapezoidal or dovetail section",
        "graph": [
            "sketch or polygon_prism with symmetric trapezoid points",
            "extrude(profile, length)",
            "optionally union a top body or cut a mating slot",
        ],
        "checks": ["top width", "base width", "taper angle", "extrusion length"],
    },
    {
        "id": "gear_like_pattern",
        "keywords": ("gear", "teeth", "tooth", "齿轮", "轮齿"),
        "intent": "repeat one tooth around a hub",
        "graph": [
            "hub cylinder",
            "one tooth profile or box tangent to the hub",
            "polar_pattern(tooth, tooth_count, axis=[0,0,1])",
            "union(hub, patterned teeth)",
        ],
        "checks": ["tooth count", "bore diameter", "outer diameter", "radial symmetry"],
    },
    {
        "id": "tank_chassis_assembly",
        "keywords": ("tank", "chassis", "turret", "barrel", "tracks", "坦克", "炮塔", "炮管", "战车"),
        "intent": "assemble a tracked vehicle with hull box, left/right track boxes extending slightly beyond hull length, top-mounted turret, and long forward-oriented barrel protruding past the hull front",
        "graph": [
            "hull box at base (width=56, depth=110, height=18 mm; X=transverse width, Y=forward length)",
            "left_track box (width=14, depth=124, height=16 mm) mounted on hull.face('<X')",
            "right_track box (width=14, depth=124, height=16 mm) mounted on hull.face('>X')",
            "turret cylinder (radius=18, height=14 mm) mounted on hull.face('>Z')",
            "barrel cylinder (radius=2.5, height=75 mm) mounted on turret.face('>Y') with orientation='forward' so it protrudes 35 mm past the hull front",
            "union(all components)",
        ],
        "checks": ["hull proportions", "turret top mounting", "barrel forward orientation", "track symmetry"],
    },
    {
        "id": "vehicle_chassis_wheels",
        "keywords": ("car", "vehicle", "wheels", "automobile", "小车", "汽车", "底盘", "车轮"),
        "intent": "assemble a 4-wheeled vehicle with chassis body, centered top cabin, and 4 vertical rolling wheels on left/right side faces separated into front (+Y) and rear (-Y) axles extending below chassis bottom",
        "graph": [
            "chassis box at base (width=50, depth=110, height=18 mm; X=transverse width, Y=forward length)",
            "cabin box (width=46, depth=55, height=16 mm) mounted on chassis.face('>Z') with align='center'",
            "wheel_fl cylinder (radius=15, height=10 mm) mounted on chassis.face('<X') with orientation='auto' and offset=[0, 35, -5]",
            "wheel_fr cylinder (radius=15, height=10 mm) mounted on chassis.face('>X') with orientation='auto' and offset=[0, 35, -5]",
            "wheel_rl cylinder (radius=15, height=10 mm) mounted on chassis.face('<X') with orientation='auto' and offset=[0, -35, -5]",
            "wheel_rr cylinder (radius=15, height=10 mm) mounted on chassis.face('>X') with orientation='auto' and offset=[0, -35, -5]",
            "union(chassis, cabin, wheel_fl, wheel_fr, wheel_rl, wheel_rr)",
        ],
        "checks": ["chassis proportions", "cabin top mounting", "wheel placement", "wheel symmetry"],
    },
    {
        "id": "pulley_bracket_assembly",
        "keywords": ("pulley", "bracket", "sheave", "clevis", "滑轮", "滑轮支架"),
        "intent": "assemble a U-bracket housing with a center shaft and grooved pulley wheel",
        "graph": [
            "u_bracket base and side flanges",
            "shaft cylinder mounted through bracket flanges",
            "grooved pulley wheel cylinder coaxial with shaft",
            "union(bracket, shaft, pulley)",
        ],
        "checks": ["bracket u-profile", "shaft alignment", "pulley coaxial mounting", "clearance"],
    },
    {
        "id": "pillow_block_bearing_housing",
        "keywords": ("bearing", "housing", "pillow", "block", "bushing", "pedestal", "轴承座", "立式轴承座", "轴承支架", "轴瓦", "轴承"),
        "intent": "assemble a pillow block bearing housing with bottom mounting base, central upright bearing sleeve arch with horizontal through-bore, and left/right ear bolt mounting slots",
        "graph": [
            "base box (width=80, depth=40, height=12 mm; X=transverse width, Y=depth)",
            "sleeve cylinder (radius=20, height=40 mm) mounted on base.face('>Z') with orientation='forward' and offset=[0, 0, 0]",
            "bore cylinder (radius=12.5, height=50 mm) coaxial with sleeve along Y (orientation='forward')",
            "slot_left box (width=8, depth=16, height=30 mm) mounted on base.face('>Z') with offset=[-28, 0, 0]",
            "slot_right box (width=8, depth=16, height=30 mm) mounted on base.face('>Z') with offset=[28, 0, 0]",
            "housing_solid = union(base, sleeve)",
            "bearing_housing = cut(housing_solid, bore, slot_left, slot_right)",
        ],
        "checks": ["base flange dimensions", "horizontal bore alignment", "ear mounting slot spacing", "bore clearance"],
    },
)


_TOKEN_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]")
_SEMANTIC_ALIASES: dict[str, tuple[str, ...]] = {
    "cooling": ("fin", "heat", "sink", "rib", "散热", "鳍片"),
    "thermal": ("fin", "heat", "sink", "散热"),
    "dissipator": ("heat", "sink", "fin", "散热片"),
    "fastener": ("hole", "bolt", "mounting", "孔", "螺栓"),
    "mounting": ("hole", "bolt", "fastener", "flange", "安装孔"),
    "holes": ("hole", "bolt", "mounting", "孔"),
    "mount": ("hole", "bolt", "flange", "安装孔"),
    "rail": ("dovetail", "slide", "燕尾", "导轨"),
    "slide": ("dovetail", "rail", "燕尾", "滑轨"),
    "rotary": ("gear", "tooth", "teeth", "齿轮"),
    "cog": ("gear", "tooth", "teeth", "齿轮"),
    "axle": ("shaft", "stepped", "传动轴", "阶梯轴"),
    "armor": ("tank", "turret", "chassis", "坦克"),
    "cannon": ("barrel", "turret", "tank", "炮管"),
    "track": ("tracks", "tank", "chassis", "履带"),
    "tracks": ("track", "tank", "chassis", "履带"),
    "treads": ("tracks", "tank", "履带"),
    "automobile": ("car", "vehicle", "wheels", "汽车"),
    "truck": ("vehicle", "car", "chassis", "wheels", "卡车"),
    "sheave": ("pulley", "bracket", "clevis", "滑轮"),
    "clevis": ("bracket", "pulley", "sheave", "支架"),
}


def _tokenize(text: str) -> list[str]:
    """Tokenize English words and CJK unigrams/bigrams for local retrieval."""
    normalized = " ".join(str(text).lower().split())
    tokens = [match.group(0) for match in _TOKEN_RE.finditer(normalized)]
    cjk_runs = re.findall(r"[\u4e00-\u9fff]+", normalized)
    for run in cjk_runs:
        tokens.extend(run[index:index + 2] for index in range(max(0, len(run) - 1)))
        tokens.extend(run[index:index + 3] for index in range(max(0, len(run) - 2)))
    expanded = list(tokens)
    for token in tokens:
        expanded.extend(_SEMANTIC_ALIASES.get(token, ()))
    return expanded


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(index, 0.0) for index, value in left.items())


class FeatureRecipeIndex:
    """Small local sparse TF-IDF vector index.

    It avoids a network call and a heavyweight model dependency while exposing
    the same cosine-search interface that can later be backed by a neural
    embedding service. Recipe content is embedded once at startup; queries are
    embedded and ranked in memory.
    """

    def __init__(self, recipes: tuple[dict[str, Any], ...] = FEATURE_RECIPES):
        self.recipes = recipes
        document_tokens = [self._recipe_tokens(recipe) for recipe in recipes]
        document_frequency: dict[str, int] = {}
        for tokens in document_tokens:
            for token in set(tokens):
                document_frequency[token] = document_frequency.get(token, 0) + 1
        self._idf = {
            token: math.log((1.0 + len(recipes)) / (1.0 + frequency)) + 1.0
            for token, frequency in document_frequency.items()
        }
        self._vectors = [self._embed_tokens(tokens) for tokens in document_tokens]
        self._keyword_tokens = [
            set(_tokenize(" ".join(str(item) for item in recipe.get("keywords", ()))) )
            for recipe in recipes
        ]

    @staticmethod
    def _recipe_tokens(recipe: dict[str, Any]) -> list[str]:
        keywords = " ".join(str(item) for item in recipe.get("keywords", ()))
        intent = str(recipe.get("intent", ""))
        text = " ".join([
            str(recipe.get("id", "")),
            # Retrieval should be driven by intent and domain terms.  Generic
            # graph words such as ``base`` or ``box`` otherwise dominate a
            # small catalog even when the feature family is unrelated.
            keywords,
            keywords,
            keywords,
            intent,
            intent,
            " ".join(str(item) for item in recipe.get("checks", ())),
        ])
        return _tokenize(text)

    def _embed_tokens(self, tokens: list[str]) -> dict[str, float]:
        vector: dict[str, float] = {}
        for token in tokens:
            vector[token] = vector.get(token, 0.0) + self._idf.get(token, 1.0)
        norm = math.sqrt(sum(value * value for value in vector.values()))
        if norm <= 1e-12:
            return {}
        return {token: value / norm for token, value in vector.items()}

    def search(self, prompt: str, limit: int = 3, min_score: float = 0.08) -> list[dict[str, Any]]:
        query_tokens = _tokenize(prompt)
        query = self._embed_tokens(query_tokens)
        query_keywords = set(query_tokens)
        scored = [
            (
                0.75 * _cosine(query, vector)
                + 0.25 * (len(query_keywords & keyword_tokens) / max(1, len(query_keywords))),
                _cosine(query, vector),
                recipe,
            )
            for recipe, vector, keyword_tokens in zip(self.recipes, self._vectors, self._keyword_tokens)
        ]
        scored.sort(key=lambda item: (-item[0], -item[1], item[2]["id"]))
        results: list[dict[str, Any]] = []
        for score, vector_score, recipe in scored[: max(1, min(limit, 8))]:
            if score < max(0.0, float(min_score)):
                continue
            item = dict(recipe)
            item["retrieval_score"] = round(float(score), 6)
            item["vector_score"] = round(float(vector_score), 6)
            item["retrieval_method"] = "local_tfidf_cosine"
            results.append(item)
        return results


FEATURE_RECIPE_INDEX = FeatureRecipeIndex()


def retrieve_feature_recipes(prompt: str, limit: int = 3, min_score: float = 0.08) -> list[dict[str, Any]]:
    """Retrieve graph recipes through local vector cosine similarity."""
    return FEATURE_RECIPE_INDEX.search(prompt, limit=limit, min_score=min_score)


__all__ = ["FEATURE_RECIPES", "retrieve_feature_recipes"]
