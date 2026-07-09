"""Tests for humanize_error and the fluid-property envelope predicates."""

import pytest

from physics.errors import PropertyRangeError, humanize_error
from physics.fluid_air import (
    AIR_T_MAX,
    AIR_T_MIN,
    air_props,
    air_temp_in_range,
)
from physics.fluid_water import (
    WATER_T_MAX,
    WATER_T_MIN,
    water_props,
    water_temp_in_range,
)


def test_air_temp_in_range():
    assert air_temp_in_range(300.0)
    assert air_temp_in_range(AIR_T_MIN)
    assert air_temp_in_range(AIR_T_MAX)
    assert not air_temp_in_range(AIR_T_MIN - 1.0)
    assert not air_temp_in_range(AIR_T_MAX + 1.0)


def test_water_temp_in_range():
    assert water_temp_in_range(320.0)
    assert water_temp_in_range(WATER_T_MIN)
    assert water_temp_in_range(WATER_T_MAX)
    assert not water_temp_in_range(WATER_T_MIN - 1.0)
    assert not water_temp_in_range(WATER_T_MAX + 1.0)


def test_humanize_rewrites_coolprop_range_error():
    # Mimics CoolProp's cryptic wording.
    raw = ValueError(
        "The input for key (12) with value (13) is outside the range of validity: (0) to (1)"
    )
    message = humanize_error(raw)
    assert "key" not in message.lower()
    assert "supported property range" in message
    assert "temperature" in message.lower()


def test_humanize_passes_through_clear_messages():
    exc = ValueError("Mass flow rates must be positive.")
    assert humanize_error(exc) == "Mass flow rates must be positive."


def test_humanize_passes_through_unrelated_range_wording():
    # A message that says "outside the range" but is not a CoolProp key error
    # should be left alone (no numeric key reference).
    exc = ValueError("Value is outside the range you expected")
    assert humanize_error(exc) == "Value is outside the range you expected"


def test_air_props_out_of_range_raises_structured_error():
    # A temperature far outside any valid moist-air range makes CoolProp fail;
    # the wrapper re-raises it as a typed PropertyRangeError (no string sniffing
    # needed downstream), which humanize_error renders as a clear message.
    with pytest.raises(PropertyRangeError) as excinfo:
        air_props(10.0)
    message = humanize_error(excinfo.value)
    assert "supported property range" in message
    assert "key" not in message.lower()


def test_water_props_out_of_range_raises_structured_error():
    with pytest.raises(PropertyRangeError) as excinfo:
        water_props(10.0)
    message = humanize_error(excinfo.value)
    assert "supported property range" in message
    assert "key" not in message.lower()
