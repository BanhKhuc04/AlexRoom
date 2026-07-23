from __future__ import annotations

import unittest

from alex_intelligence import IntelligenceRoute, route_intelligence


class IntelligenceRouterTests(unittest.TestCase):
    def test_routes_simple_calculator_addition(self) -> None:
        decision = route_intelligence("2 + 2")
        self.assertEqual(decision.route, IntelligenceRoute.CALCULATOR)

    def test_routes_multiplication_with_x(self) -> None:
        decision = route_intelligence("128 x 372")
        self.assertEqual(decision.route, IntelligenceRoute.CALCULATOR)

    def test_routes_system_status_query_to_system_status_tool(self) -> None:
        decision = route_intelligence("Cho toi xem trang thai he thong ALEX.")
        self.assertEqual(decision.route, IntelligenceRoute.SYSTEM)
        self.assertEqual(decision.allowed_tool_names, ("system_status",))

    def test_routes_alex_health_question_to_system_status_tool(self) -> None:
        decision = route_intelligence("ALEX co on khong?")
        self.assertEqual(decision.route, IntelligenceRoute.SYSTEM)
        self.assertEqual(decision.allowed_tool_names, ("system_status",))

    def test_routes_device_online_question_to_list_devices_tool(self) -> None:
        decision = route_intelligence("ESP01 online khong?")
        self.assertEqual(decision.route, IntelligenceRoute.SYSTEM)
        self.assertEqual(decision.allowed_tool_names, ("list_devices",))

    def test_routes_device_listing_question_to_list_devices_tool(self) -> None:
        decision = route_intelligence("liet ke thiet bi")
        self.assertEqual(decision.route, IntelligenceRoute.SYSTEM)
        self.assertEqual(decision.allowed_tool_names, ("list_devices",))

    def test_routes_time_question(self) -> None:
        decision = route_intelligence("may gio roi?")
        self.assertEqual(decision.route, IntelligenceRoute.TIME)

    def test_routes_today_date_question(self) -> None:
        decision = route_intelligence("hom nay ngay bao nhieu?")
        self.assertEqual(decision.route, IntelligenceRoute.TIME)

    def test_routes_weather_question(self) -> None:
        decision = route_intelligence("thoi tiet Ha Noi hom nay the nao?")
        self.assertEqual(decision.route, IntelligenceRoute.WEATHER)

    def test_routes_rain_question(self) -> None:
        decision = route_intelligence("mai co mua khong?")
        self.assertEqual(decision.route, IntelligenceRoute.WEATHER)

    def test_falls_back_to_llm_for_general_analysis(self) -> None:
        decision = route_intelligence("giai thich tai sao he thong nay cham")
        self.assertEqual(decision.route, IntelligenceRoute.LLM)
        self.assertFalse(decision.matched)

    def test_guarded_test_led_command_stays_on_llm_path(self) -> None:
        decision = route_intelligence("bat den test")
        self.assertEqual(decision.route, IntelligenceRoute.LLM)
        self.assertEqual(decision.allowed_tool_names, ())

    def test_guarded_relay_command_stays_on_llm_path(self) -> None:
        decision = route_intelligence("bat relay_1")
        self.assertEqual(decision.route, IntelligenceRoute.LLM)
        self.assertEqual(decision.allowed_tool_names, ())

    def test_empty_string_falls_back_safely(self) -> None:
        decision = route_intelligence("")
        self.assertEqual(decision.route, IntelligenceRoute.LLM)

    def test_whitespace_only_string_falls_back_safely(self) -> None:
        decision = route_intelligence("   ")
        self.assertEqual(decision.route, IntelligenceRoute.LLM)


if __name__ == "__main__":
    unittest.main()
