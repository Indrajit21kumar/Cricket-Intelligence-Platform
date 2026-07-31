"""Coach dashboard composition (M18 Step 4, FR-M18-03, AC-M18-04)."""

from __future__ import annotations

import uuid

from academy_service.domain.dashboard import compose_dashboard


class TestComposeDashboard:
    def test_composes_all_four_sources(self) -> None:
        person_id = uuid.uuid4()
        scores = {"overall": {"value": 72.0}}
        dna_traits = {"balance": {"value": "0.6"}}
        plan = {"stage": "foundation"}

        dashboard = compose_dashboard(
            person_id=person_id,
            display_name="Kavya",
            scores=scores,
            dna_traits=dna_traits,
            active_plan=plan,
        )

        assert dashboard.person_id == person_id
        assert dashboard.display_name == "Kavya"
        assert dashboard.scores == scores
        assert dashboard.dna_traits == dna_traits
        assert dashboard.active_plan == plan

    def test_a_player_with_no_report_yet_has_none_scores(self) -> None:
        dashboard = compose_dashboard(
            person_id=uuid.uuid4(),
            display_name="Rohan",
            scores=None,
            dna_traits={},
            active_plan=None,
        )
        assert dashboard.scores is None
        assert dashboard.dna_traits == {}
        assert dashboard.active_plan is None

    def test_to_dict_shape(self) -> None:
        person_id = uuid.uuid4()
        dashboard = compose_dashboard(
            person_id=person_id,
            display_name="Kavya",
            scores={"overall": {"value": 72.0}},
            dna_traits={"balance": {"value": "0.6"}},
            active_plan={"stage": "foundation"},
        )
        assert dashboard.to_dict() == {
            "person_id": str(person_id),
            "display_name": "Kavya",
            "scores": {"overall": {"value": 72.0}},
            "dna_traits": {"balance": {"value": "0.6"}},
            "active_plan": {"stage": "foundation"},
        }

    def test_to_dict_with_no_data_yet(self) -> None:
        person_id = uuid.uuid4()
        dashboard = compose_dashboard(
            person_id=person_id,
            display_name=None,
            scores=None,
            dna_traits={},
            active_plan=None,
        )
        assert dashboard.to_dict() == {
            "person_id": str(person_id),
            "display_name": None,
            "scores": None,
            "dna_traits": {},
            "active_plan": None,
        }
