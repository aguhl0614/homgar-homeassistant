"""Tests for HTV145FRF water usage calibration."""

from custom_components.homgar.devices import HTV145FRF


def _make_device() -> HTV145FRF:
    return HTV145FRF(
        model="HTV145FRF",
        model_code=302,
        name="Garden",
        did="520181282",
        mid="237869",
        alerts=[],
        address=1,
        port_number=1,
    )


def test_htv145frf_water_usage_matches_calibration_points() -> None:
    """Known tail values should map to the app's reported gallons exactly."""
    device = _make_device()

    cases = [
        ("9F03000000", 927, 0.1),
        ("9F1B000000", 7071, 0.7),
        ("9F2B000000", 11167, 1.1),
        ("9F51000000", 20895, 2.1),
        ("9F59000000", 22943, 2.4),
        ("9F74000000", 29855, 3.1),
        ("9FB0000000", 45215, 4.6),
        ("9FE6000000", 59039, 6.1),
    ]

    for tail_hex, tail_value, gallons in cases:
        device._parse_device_specific_status_d_value(f"11#000000D800AD0000{tail_hex}")
        assert device.candidate_tail_hex == tail_hex
        assert device.candidate_tail_value == tail_value
        assert device.water_usage_gallons == gallons


def test_htv145frf_water_usage_interpolates_between_points() -> None:
    """Unknown tail values should be interpolated between the nearest calibration points."""
    gallons = HTV145FRF._estimate_water_usage_gallons(16031)

    assert gallons == 1.6
