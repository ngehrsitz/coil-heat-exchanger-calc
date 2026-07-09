"""Register geometry — inputs and derived quantities.

RegisterGeometry holds only the independent geometric parameters needed to
fully describe the fin-and-tube coil. All other quantities (areas, diameters,
counts) are computed by derive_geometry() and stored in DerivedGeometry.

The coil frontal area is derived as:
    frontal_area = tubes_per_row × hole_pitch × coil_length
This is the active heat-transfer face, not the outer casing dimensions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Floor for the air-side minimum free-flow area [m²]. Guards a degenerate
# geometry (tube + fin blockage exceeding the frontal area) from producing a
# non-positive area that would divide by zero downstream. The cross-field
# sanity checks live in RegisterGeometry.validate(); this is a last-resort
# numeric floor, deliberately tiny so any real geometry is unaffected.
_MIN_FREE_FLOW_AREA_M2 = 1e-6


@dataclass(frozen=True)
class RegisterGeometry:
    # Tube layout
    rows: int = 6
    tubes_per_row: int = 10
    coil_length: float = 0.300  # m  (fin height / coil width)

    # Tube dimensions  (copper)
    tube_od: float = 0.00952  # m
    tube_wall: float = 0.0006  # m  (assumed)

    # Fin dimensions  (corrugated dimpled aluminium)
    fin_pitch: float = 0.0025  # m  (centre-to-centre)
    fin_thickness: float = 0.0001  # m  (100 µm)
    fin_conductivity: float = 205.0  # W/m·K

    # Tube layout pitches
    row_pitch: float = 0.022  # m  (depth direction, between row centres)
    hole_pitch: float = 0.0254  # m  (transverse, between tube centres)

    # Tube material
    tube_conductivity: float = 385.0  # W/m·K  (copper)

    def validate(self) -> list[tuple[str, str]]:
        """Return geometry inconsistencies as ``(field, message)`` pairs.

        Covers only the cross-field constraints that would otherwise produce a
        degenerate coil in ``derive_geometry`` (a non-positive tube bore or fin
        gap). Independent per-field bounds are the caller's responsibility. The
        ``field`` names match this dataclass's attributes so a UI can map each
        error back to the offending input.
        """
        errors: list[tuple[str, str]] = []
        if self.tube_wall >= self.tube_od / 2.0:
            # tube_id = tube_od − 2·tube_wall would be ≤ 0
            errors.append(("tube_wall", "Tube wall must be less than half the tube OD."))
        if self.fin_thickness >= self.fin_pitch:
            # fin_pitch_clear = fin_pitch − fin_thickness would be ≤ 0
            errors.append(("fin_thickness", "Fin thickness must be less than fin pitch."))
        if self.tube_od >= self.hole_pitch:
            errors.append(("hole_pitch", "Hole pitch must be greater than tube OD."))

        tube_hole_area = math.pi / 4.0 * self.tube_od**2
        pitch_cell_area = self.hole_pitch * self.row_pitch
        if tube_hole_area >= pitch_cell_area:
            errors.append(("row_pitch", "Tube holes must fit within the tube pitch cell."))

        if self.fin_pitch > 0.0 and self.fin_thickness < self.fin_pitch:
            frontal_area = self.tubes_per_row * self.hole_pitch * self.coil_length
            n_fins = self.coil_length / self.fin_pitch
            transverse_gap = self.tubes_per_row * (self.hole_pitch - self.tube_od)
            fin_blockage = n_fins * self.fin_thickness * transverse_gap
            free_flow_area = frontal_area - (self.tubes_per_row * self.tube_od * self.coil_length)
            free_flow_area -= fin_blockage
            if free_flow_area <= 0.0:
                errors.append(
                    ("tube_od", "Tube and fin blockage must leave positive air flow area.")
                )
        return errors


@dataclass(frozen=True)
class DerivedGeometry:
    total_tubes: int

    tube_id: float  # m   = tube_od - 2×tube_wall

    # Air-side areas
    frontal_area: float  # m²  = tubes_per_row × hole_pitch × coil_length
    #       (active coil face, not outer casing)
    min_free_flow_area: float  # m²  minimum free-flow cross-section for air
    sigma: float  # —   Ac/Afr  contraction ratio

    total_ext_area: float  # m²  total external surface (fins + bare tube)
    fin_area: float  # m²  fin surface area
    bare_area: float  # m²  unfinned tube external surface

    dh_ext: float  # m   hydraulic diameter, air side

    # Water-side areas
    tube_int_area: float  # m²  total internal tube surface area
    dh_int: float  # m   = tube_id  (circular cross-section)

    # Overall coil depth
    depth: float  # m   = rows × row_pitch


def derive_geometry(g: RegisterGeometry) -> DerivedGeometry:
    """Compute all derived geometric quantities from the independent inputs."""
    errors = g.validate()
    if errors:
        raise ValueError(
            "Invalid register geometry: " + "; ".join(message for _, message in errors)
        )

    tube_id = g.tube_od - 2.0 * g.tube_wall
    total_tubes = g.rows * g.tubes_per_row

    # --- Air-side geometry ---
    # Frontal (face) area = active fin face
    frontal_area = g.tubes_per_row * g.hole_pitch * g.coil_length

    # Number of fins along coil length
    n_fins = g.coil_length / g.fin_pitch  # continuous count

    # Fin area (both faces of each fin, minus tube holes)
    tube_hole_area = math.pi / 4.0 * g.tube_od**2
    # Total fin area = n_fins × (area of one fin × tubes_per_row − tube holes) × 2 faces
    # One fin spans the full transverse width (tubes_per_row × hole_pitch) × coil_length/n_fins height
    # Simplified per standard formulation:
    fin_area = (
        2.0
        * n_fins
        * (g.tubes_per_row * g.hole_pitch * (g.row_pitch * g.rows) - total_tubes * tube_hole_area)
    )

    # Bare tube area (unfinned external tube surface between fins)
    tube_ext_per_row_length = math.pi * g.tube_od * g.coil_length
    # Fraction of tube exposed (not covered by fins)
    fin_pitch_clear = g.fin_pitch - g.fin_thickness
    bare_fraction = fin_pitch_clear / g.fin_pitch
    bare_area = total_tubes * tube_ext_per_row_length * bare_fraction

    total_ext_area = fin_area + bare_area

    # Minimum free-flow area (frontal area minus tube and fin blockage)
    # Blockage from fin thickness
    fin_blockage = (
        n_fins * g.fin_thickness * (g.tubes_per_row * g.hole_pitch - g.tubes_per_row * g.tube_od)
    )
    min_free_flow_area = frontal_area - (g.tubes_per_row * g.tube_od * g.coil_length) - fin_blockage
    min_free_flow_area = max(min_free_flow_area, _MIN_FREE_FLOW_AREA_M2)

    sigma = min_free_flow_area / frontal_area

    # Hydraulic diameter (air side): 4 × Ac × depth / total_ext_area
    depth = g.rows * g.row_pitch
    dh_ext = 4.0 * min_free_flow_area * depth / total_ext_area

    # --- Water-side geometry ---
    tube_int_area = total_tubes * math.pi * tube_id * g.coil_length
    dh_int = tube_id

    return DerivedGeometry(
        total_tubes=total_tubes,
        tube_id=tube_id,
        frontal_area=frontal_area,
        min_free_flow_area=min_free_flow_area,
        sigma=sigma,
        total_ext_area=total_ext_area,
        fin_area=fin_area,
        bare_area=bare_area,
        dh_ext=dh_ext,
        tube_int_area=tube_int_area,
        dh_int=dh_int,
        depth=depth,
    )
