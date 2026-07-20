from pathlib import Path
import re
import unittest


TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "admin_import_panel.html"


class AdminPromaxSchedulePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = TEMPLATE_PATH.read_text(encoding="utf-8")

    def test_schedule_supports_resellers_groups_and_completion_triggers(self) -> None:
        field_ids = (
            "promaxScheduleCategories",
            "promaxScheduleStartDate",
            "promaxScheduleEndDate",
            "promaxScheduleSendDates",
            "promaxScheduleResellers",
            "promaxScheduleRoutines",
            "promaxSchedulePublish",
            "promaxScheduleTriggerType",
            "promaxScheduleTriggerSchedule",
        )
        for field_id in field_ids:
            with self.subTest(field_id=field_id):
                self.assertEqual(self.html.count(f'id="{field_id}"'), 1)

        self.assertIn("promaxScheduleChainPayload()", self.html)
        self.assertIn('scheduleChains: "/api/admin/promax/schedule-chains"', self.html)
        self.assertIn(
            'E.promaxScheduleTriggerType.addEventListener("change", syncPromaxScheduleFields);',
            self.html,
        )

    def test_dates_are_opt_in_for_run_now_and_schedules(self) -> None:
        for field_id in ("promaxSendDates", "promaxScheduleSendDates"):
            with self.subTest(field_id=field_id):
                self.assertEqual(self.html.count(f'id="{field_id}"'), 1)
                match = re.search(
                    rf"<input\b[^>]*\bid=\"{re.escape(field_id)}\"[^>]*>",
                    self.html,
                )
                self.assertIsNotNone(match)
                input_tag = match.group(0) if match else ""
                self.assertNotIn("checked", input_tag)

        self.assertIn("function syncPromaxDateFields()", self.html)
        self.assertIn(
            "send_dates: Boolean(E.promaxSendDates && E.promaxSendDates.checked)",
            self.html,
        )
        self.assertIn(
            "send_dates: Boolean(E.promaxScheduleSendDates && E.promaxScheduleSendDates.checked)",
            self.html,
        )

    def test_execution_log_filters_by_date_range(self) -> None:
        for field_id in (
            "promaxJobStatusFilter",
            "promaxJobFromDate",
            "promaxJobToDate",
            "promaxJobClearFiltersBtn",
        ):
            with self.subTest(field_id=field_id):
                self.assertEqual(self.html.count(f'id="{field_id}"'), 1)

        self.assertIn('params.set("created_from", createdFrom)', self.html)
        self.assertIn('params.set("created_to", createdTo)', self.html)
        self.assertIn("function clearPromaxJobFilters()", self.html)

    def test_execution_log_has_retry_and_unit_summary_modal(self) -> None:
        for field_id in (
            "promaxUnitsModal",
            "promaxUnitsModalTitle",
            "promaxUnitsModalSubtitle",
            "promaxUnitsModalBody",
        ):
            with self.subTest(field_id=field_id):
                self.assertEqual(self.html.count(f'id="{field_id}"'), 1)

        self.assertIn('function promaxRetryJob(jobId)', self.html)
        self.assertIn('function promaxOpenUnitsModal(jobId)', self.html)
        self.assertIn('/retry`, {', self.html)
        self.assertIn('promaxJobUnitSummary(job)', self.html)
        self.assertIn('promax-unit-status', self.html)

    def test_promax_admin_uses_scoped_neutral_colors(self) -> None:
        self.assertIn("#promaxPane {", self.html)
        self.assertIn("--promax-neutral-bg: #f5f6f8;", self.html)
        self.assertIn(".promax-status--danger", self.html)
        self.assertIn(
            '<span class="promax-status ${promaxStatusClass(status)}">',
            self.html,
        )

    def test_schedule_uses_searchable_power_bi_style_slicers(self) -> None:
        for prefix in (
            "promaxScheduleReseller",
            "promaxScheduleCategory",
            "promaxScheduleRoutine",
        ):
            with self.subTest(prefix=prefix):
                for suffix in (
                    "Slicer",
                    "Button",
                    "Panel",
                    "Search",
                    "SelectAllBtn",
                    "ClearBtn",
                ):
                    self.assertEqual(self.html.count(f'id="{prefix}{suffix}"'), 1)

        self.assertIn('setupPromaxScheduleSlicerEvents("schedule")', self.html)
        self.assertIn("selectVisiblePromaxScheduleSlicerOptions", self.html)
        self.assertIn("clearPromaxScheduleSlicerSelection", self.html)
        self.assertIn('renderPromaxScheduleSlicer("routine", scope)', self.html)

    def test_run_now_uses_the_same_slicers_and_batch_endpoint(self) -> None:
        for prefix in (
            "promaxRunReseller",
            "promaxRunCategory",
            "promaxRunRoutine",
        ):
            with self.subTest(prefix=prefix):
                for suffix in (
                    "Slicer",
                    "Button",
                    "Panel",
                    "Search",
                    "SelectAllBtn",
                    "ClearBtn",
                ):
                    self.assertEqual(self.html.count(f'id="{prefix}{suffix}"'), 1)

        self.assertIn('jobsBatch: "/api/admin/promax/jobs/batch"', self.html)
        self.assertIn("promaxRunBatchPayload()", self.html)
        self.assertIn('setupPromaxScheduleSlicerEvents("run")', self.html)
        self.assertIn("payload.groups.length", self.html)

    def test_schedule_exposes_all_supported_resellers(self) -> None:
        reseller_codes = (
            "0640001",
            "0640002",
            "2210003",
            "2210004",
            "3480005",
            "3610006",
            "3610007",
            "3610008",
        )
        for reseller_code in reseller_codes:
            with self.subTest(reseller_code=reseller_code):
                self.assertIn(f'id: "{reseller_code}"', self.html)

    def test_schedule_list_identifies_the_report_group(self) -> None:
        self.assertIn("<th>Grupo</th>", self.html)
        self.assertIn("<th>Revendas</th>", self.html)
        self.assertIn("<th>Gatilho</th>", self.html)
        self.assertIn("schedule.job_type || schedulePayload.category", self.html)


if __name__ == "__main__":
    unittest.main()
