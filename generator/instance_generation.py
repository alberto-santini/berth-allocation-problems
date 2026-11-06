from __future__ import annotations

import argparse
import json
import math
import zlib
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


GENERATOR_DIR = Path(__file__).resolve().parent
DEFAULT_RAW_DATA_PATH = GENERATOR_DIR / "raw" / "Barcelona_2024.csv"
DEFAULT_INSTANCES_ROOT = GENERATOR_DIR.parent / "instances"

QUAY_BERTHS_TOTAL = {
    "36A": 31,
    "24B": 23,
}
QUAY_BERTHS_UNUSED = {
    "36A": 2,
    "24B": 3,
}
QUAYS = tuple(QUAY_BERTHS_TOTAL)
WEEK_STARTS = range(2, 51)
DENSITY_PERCENTAGES = (100, 90, 80, 70, 60, 50)

DISCRETISATION_HOURS = 1
EXTREME_QUAY_FRACTION = 0.15
EXTREME_HANDLING_FACTOR = 1.20
RANDOM_SEED = 2024

UNIFORM_WEIGHT_MIN = 1
UNIFORM_WEIGHT_MAX = 10
UNIMPORTANT_WEIGHT = 1
IMPORTANT_WEIGHT = 10
TOP_QUARTILE_PROBABILITY = 0.50
OTHER_SHIPS_PROBABILITY = 0.10

WEIGHT_REGIMES = ("unit", "uniform", "important")
WEIGHTED_SUM_WAITING_HANDLING = "WeightedSumWaitingHandling"
WEIGHTED_SUM_WAITING_TARDINESS = "WeightedSumWaitingTardiness"

OUTPUT_FOLDERS = {
    ("fix", "max-compl"): "hyb_dyn_fix_max-compl",
    ("pos", "max-compl"): "hyb_dyn_pos_max-compl",
    ("fix", "sum-wait-hand"): "hyb_dyn_fix_sum-wait-hand",
    ("pos", "sum-wait-hand"): "hyb_dyn_pos_sum-wait-hand",
    ("fix", "sum-wait-tard"): "hyb_dyn_fix_sum-wait-tard",
    ("pos", "sum-wait-tard"): "hyb_dyn_pos_sum-wait-tard",
}
SHIP_FIELDS = (
    "arrival_time",
    "handling_time",
    "ship_len",
    "ship_importance",
    "desired_completion_time",
)


def load_calls(path: Path = DEFAULT_RAW_DATA_PATH) -> pd.DataFrame:
    calls = pd.read_csv(
        path,
        parse_dates=["ETAUTC", "ETDUTC"],
        decimal=",",
    )
    calls = calls[~calls.TERMINALCODI.isna()]
    calls = calls[~calls.MOLLMODULS.isna()]
    calls = calls[calls.ANYESCALA == 2024]
    calls = calls[calls.ESCALAESTAT == "Finalitzada"]
    calls = calls[calls.VAIXELLTIPUS == "Portacontenidors"]
    calls = calls[calls.MOLLCODI.isin(QUAYS)]
    calls = calls[
        [
            "TERMINALCODI",
            "TERMINALNOM",
            "ETAUTC",
            "ETDUTC",
            "MOLLCODI",
            "ESLORA_METRES",
            "CALAT_METRES",
            "MANEGA_METRES",
            "MOLLMODULS",
            "ESCALANUM",
        ]
    ]
    calls = calls.rename(
        columns={
            "TERMINALCODI": "terminal_code",
            "TERMINALNOM": "terminal_name",
            "ETAUTC": "eta_utc",
            "ETDUTC": "etd_utc",
            "MOLLCODI": "berth_code",
            "ESLORA_METRES": "ship_length",
            "CALAT_METRES": "ship_draught",
            "MANEGA_METRES": "ship_width",
            "MOLLMODULS": "berth_modulus",
            "ESCALANUM": "call_num",
        }
    )
    calls["call_time"] = calls.etd_utc - calls.eta_utc
    calls = calls[calls.call_time <= pd.Timedelta(hours=48)].copy()
    calls[["modulus_start", "modulus_end"]] = calls.berth_modulus.str.split(
        "-", expand=True
    )
    calls["modulus_start"] = calls.modulus_start.astype(int)
    calls["modulus_end"] = calls.modulus_end.astype(int)
    calls["modulus_used"] = calls.modulus_end - calls.modulus_start + 1
    return calls


def generate_quay_info(quay_code: str) -> dict[str, Any]:
    n_berths = QUAY_BERTHS_TOTAL[quay_code] - QUAY_BERTHS_UNUSED[quay_code]
    return {
        "n_berths": n_berths,
        "berth_len": [1] * n_berths,
    }


def period_index(relative_time: timedelta) -> int:
    return int(
        np.floor(
            relative_time.total_seconds()
            / (3600 * DISCRETISATION_HOURS)
        )
    )


def inclusive_handling_time(
    start_relative: timedelta,
    end_relative: timedelta,
) -> int:
    if end_relative < start_relative:
        raise ValueError("handling cannot finish before it starts")

    return period_index(end_relative) - period_index(start_relative) + 1


def generate_base_instance(
    calls: pd.DataFrame,
    quay_code: str,
    week_start: int,
) -> dict[str, Any]:
    data = generate_quay_info(quay_code)

    time_horizon_begin = datetime.strptime(
        f"2024-W{week_start}-1", "%Y-W%W-%w"
    )
    time_horizon_end = time_horizon_begin + timedelta(days=14)

    selected_calls = calls[
        (calls.berth_code == quay_code)
        & (calls.eta_utc >= time_horizon_begin)
        & (calls.etd_utc <= time_horizon_end)
    ].copy()
    selected_calls["eta_relative"] = (
        selected_calls.eta_utc - time_horizon_begin
    )
    selected_calls["etd_relative"] = (
        selected_calls.etd_utc - time_horizon_begin
    )

    ships = []
    for row in selected_calls.itertuples():
        eta_relative = row.eta_relative
        if eta_relative.total_seconds() >= 7 * 24 * 60 * 60:
            eta_relative -= timedelta(days=7)

        ships.append(
            {
                "arrival_time": period_index(eta_relative),
                "handling_time": inclusive_handling_time(
                    start_relative=row.eta_relative,
                    end_relative=row.etd_relative,
                ),
                "length": int(row.modulus_used),
            }
        )

    data["n_ships"] = len(ships)
    data["n_periods"] = int(
        np.ceil(2 * 7 * 24 / DISCRETISATION_HOURS)
    )
    data["arrival_time"] = [ship["arrival_time"] for ship in ships]
    data["handling_time"] = [ship["handling_time"] for ship in ships]
    data["ship_len"] = [ship["length"] for ship in ships]
    return data


def ship_permutation(
    n_ships: int,
    quay_code: str,
    week_start: int,
    random_seed: int = RANDOM_SEED,
) -> list[int]:
    quay_seed = int.from_bytes(quay_code.encode("ascii"), byteorder="big")
    seed = np.random.SeedSequence([random_seed, quay_seed, week_start])
    return np.random.default_rng(seed).permutation(n_ships).tolist()


def instance_rng(
    quay_code: str,
    week_start: int,
    density_percentage: int,
    purpose: str,
    random_seed: int = RANDOM_SEED,
) -> np.random.Generator:
    quay_seed = int.from_bytes(quay_code.encode("ascii"), byteorder="big")
    purpose_seed = zlib.crc32(purpose.encode("utf-8"))
    seed = np.random.SeedSequence(
        [
            random_seed,
            quay_seed,
            week_start,
            density_percentage,
            purpose_seed,
        ]
    )
    return np.random.default_rng(seed)


def number_of_ships_to_keep(n_ships: int, density_percentage: int) -> int:
    if not 0 < density_percentage <= 100:
        raise ValueError("density_percentage must be in the interval [1, 100]")
    return math.floor(n_ships * density_percentage / 100 + 0.5)


def sparsify_instance(
    instance: dict[str, Any],
    density_percentage: int,
    permutation: Iterable[int],
) -> dict[str, Any]:
    n_ships = instance["n_ships"]
    permutation = list(permutation)
    if sorted(permutation) != list(range(n_ships)):
        raise ValueError("permutation must contain every ship index exactly once")

    keep_count = number_of_ships_to_keep(n_ships, density_percentage)
    kept_ship_indices = sorted(permutation[:keep_count])

    sparse = deepcopy(instance)
    sparse["n_ships"] = keep_count
    for field in SHIP_FIELDS:
        if field in sparse:
            sparse[field] = [
                sparse[field][ship_index]
                for ship_index in kept_ship_indices
            ]
    return sparse


def position_handling_times(
    handling_times: Iterable[int],
    ship_lengths: Iterable[int],
    n_berths: int,
    extreme_fraction: float = EXTREME_QUAY_FRACTION,
    extreme_factor: float = EXTREME_HANDLING_FACTOR,
) -> list[list[int]]:
    if not 0 < extreme_fraction < 0.5:
        raise ValueError("extreme_fraction must be in the interval (0, 0.5)")
    if extreme_factor <= 1:
        raise ValueError("extreme_factor must be greater than 1")

    handling_times = list(handling_times)
    ship_lengths = list(ship_lengths)
    if len(handling_times) != len(ship_lengths):
        raise ValueError("handling_times and ship_lengths must have equal size")

    extreme_width = math.ceil(n_berths * extreme_fraction)
    right_extreme_start = n_berths - extreme_width
    matrix = []
    for handling_time, ship_length in zip(handling_times, ship_lengths):
        increased_time = math.ceil(handling_time * extreme_factor)
        matrix.append(
            [
                (
                    increased_time
                    if berth < extreme_width
                    or berth + ship_length > right_extreme_start
                    else handling_time
                )
                for berth in range(n_berths)
            ]
        )
    return matrix


def make_position_instance(
    instance: dict[str, Any],
    extreme_fraction: float = EXTREME_QUAY_FRACTION,
    extreme_factor: float = EXTREME_HANDLING_FACTOR,
) -> dict[str, Any]:
    position_instance = deepcopy(instance)
    position_instance["handling_time"] = position_handling_times(
        handling_times=instance["handling_time"],
        ship_lengths=instance["ship_len"],
        n_berths=instance["n_berths"],
        extreme_fraction=extreme_fraction,
        extreme_factor=extreme_factor,
    )
    return position_instance


def unit_weights(n_ships: int) -> list[int]:
    return [1] * n_ships


def uniform_weights(
    n_ships: int,
    rng: np.random.Generator,
    minimum: int = UNIFORM_WEIGHT_MIN,
    maximum: int = UNIFORM_WEIGHT_MAX,
) -> list[int]:
    if minimum <= 0 or maximum < minimum:
        raise ValueError("weight bounds must satisfy 0 < minimum <= maximum")
    return rng.integers(minimum, maximum + 1, size=n_ships).tolist()


def top_quartile_ship_indices(
    ship_lengths: Iterable[int],
    rng: np.random.Generator,
) -> set[int]:
    lengths = list(ship_lengths)
    if not lengths:
        return set()

    top_quartile_size = math.ceil(len(lengths) / 4)
    random_tie_breakers = rng.random(len(lengths))
    ranked_indices = sorted(
        range(len(lengths)),
        key=lambda ship: (-lengths[ship], random_tie_breakers[ship]),
    )
    return set(ranked_indices[:top_quartile_size])


def importance_weights(
    ship_lengths: Iterable[int],
    rng: np.random.Generator,
    important_weight: int = IMPORTANT_WEIGHT,
    unimportant_weight: int = UNIMPORTANT_WEIGHT,
) -> list[int]:
    lengths = list(ship_lengths)
    if important_weight <= unimportant_weight or unimportant_weight <= 0:
        raise ValueError(
            "weights must satisfy 0 < unimportant_weight < important_weight"
        )

    top_quartile = top_quartile_ship_indices(lengths, rng)
    importance_draws = rng.random(len(lengths))
    return [
        (
            important_weight
            if importance_draws[ship]
            < (
                TOP_QUARTILE_PROBABILITY
                if ship in top_quartile
                else OTHER_SHIPS_PROBABILITY
            )
            else unimportant_weight
        )
        for ship in range(len(lengths))
    ]


def generate_weight_profiles(
    ship_lengths: Iterable[int],
    quay_code: str,
    week_start: int,
    density_percentage: int,
    random_seed: int = RANDOM_SEED,
) -> dict[str, list[int]]:
    lengths = list(ship_lengths)
    return {
        "unit": unit_weights(len(lengths)),
        "uniform": uniform_weights(
            n_ships=len(lengths),
            rng=instance_rng(
                quay_code=quay_code,
                week_start=week_start,
                density_percentage=density_percentage,
                purpose="uniform-weights",
                random_seed=random_seed,
            ),
        ),
        "important": importance_weights(
            ship_lengths=lengths,
            rng=instance_rng(
                quay_code=quay_code,
                week_start=week_start,
                density_percentage=density_percentage,
                purpose="importance-weights",
                random_seed=random_seed,
            ),
        ),
    }


def minimum_handling_times(
    handling_times: Iterable[int | Iterable[int]],
) -> list[int]:
    minimum_times = []
    for handling_time in handling_times:
        if isinstance(handling_time, (int, np.integer)):
            minimum_times.append(int(handling_time))
        else:
            berth_times = list(handling_time)
            if not berth_times:
                raise ValueError("position-based handling-time rows cannot be empty")
            minimum_times.append(min(berth_times))
    return minimum_times


def desired_completion_times(
    arrival_times: Iterable[int],
    handling_times: Iterable[int | Iterable[int]],
    n_periods: int,
    rng: np.random.Generator,
) -> list[int]:
    arrivals = list(arrival_times)
    minimum_times = minimum_handling_times(handling_times)
    if len(arrivals) != len(minimum_times):
        raise ValueError("arrival_times and handling_times must have equal size")

    desired_times = []
    for arrival, minimum_time in zip(arrivals, minimum_times):
        earliest_completion = arrival + minimum_time
        maximum_slack = min(
            minimum_time,
            max(0, n_periods - earliest_completion),
        )
        slack = int(rng.integers(0, maximum_slack + 1))
        desired_times.append(earliest_completion + slack)
    return desired_times


def make_weighted_objective_instance(
    instance: dict[str, Any],
    objective_function: str,
    weights: Iterable[int],
    desired_times: Iterable[int] | None = None,
) -> dict[str, Any]:
    weights = list(weights)
    if len(weights) != instance["n_ships"]:
        raise ValueError("weights must contain one value per ship")
    if objective_function not in (
        WEIGHTED_SUM_WAITING_HANDLING,
        WEIGHTED_SUM_WAITING_TARDINESS,
    ):
        raise ValueError(f"unsupported weighted objective {objective_function}")

    objective_instance = deepcopy(instance)
    objective_instance["objective_function"] = objective_function
    objective_instance["ship_importance"] = weights

    if objective_function == WEIGHTED_SUM_WAITING_TARDINESS:
        if desired_times is None:
            raise ValueError(
                "desired_times are required for waiting-tardiness instances"
            )
        desired_times = list(desired_times)
        if len(desired_times) != instance["n_ships"]:
            raise ValueError("desired_times must contain one value per ship")
        objective_instance["desired_completion_time"] = desired_times
    elif desired_times is not None:
        raise ValueError(
            "desired_times are only valid for waiting-tardiness instances"
        )

    return objective_instance


def instance_filename(
    quay_code: str,
    week_start: int,
    density_percentage: int,
    weight_regime: str | None = None,
) -> str:
    weight_suffix = f"_{weight_regime}" if weight_regime is not None else ""
    return (
        f"bcn_{quay_code}_{week_start}_{density_percentage}"
        f"{weight_suffix}.json"
    )


def _prepare_output_folders(
    instances_root: Path,
) -> dict[tuple[str, str], Path]:
    output_folders = {
        attributes: instances_root / folder_name
        for attributes, folder_name in OUTPUT_FOLDERS.items()
    }
    for output_folder in output_folders.values():
        output_folder.mkdir(parents=True, exist_ok=True)
        for stale_instance in output_folder.glob("bcn_*.json"):
            stale_instance.unlink()
    return output_folders


def write_instance(instance: dict[str, Any], path: Path) -> None:
    with path.open(mode="w", encoding="utf-8") as output:
        json.dump(instance, output, indent=2)
        output.write("\n")


def generate_all_instances(
    raw_data_path: Path = DEFAULT_RAW_DATA_PATH,
    instances_root: Path = DEFAULT_INSTANCES_ROOT,
    density_percentages: Iterable[int] = DENSITY_PERCENTAGES,
    random_seed: int = RANDOM_SEED,
    extreme_fraction: float = EXTREME_QUAY_FRACTION,
    extreme_factor: float = EXTREME_HANDLING_FACTOR,
) -> None:
    densities = tuple(dict.fromkeys(density_percentages))
    if 100 not in densities:
        raise ValueError("density_percentages must include the 100% base instances")
    if any(
        not isinstance(density_percentage, int)
        or not 0 < density_percentage <= 100
        for density_percentage in densities
    ):
        raise ValueError(
            "density percentages must be integers in the interval [1, 100]"
        )

    sparse_densities = tuple(
        density_percentage
        for density_percentage in densities
        if density_percentage != 100
    )
    calls = load_calls(raw_data_path)
    output_folders = _prepare_output_folders(instances_root)

    for quay_code in QUAYS:
        for week_start in WEEK_STARTS:
            base_instance = generate_base_instance(
                calls=calls,
                quay_code=quay_code,
                week_start=week_start,
            )
            permutation = ship_permutation(
                n_ships=base_instance["n_ships"],
                quay_code=quay_code,
                week_start=week_start,
                random_seed=random_seed,
            )
            position_instance = make_position_instance(
                instance=base_instance,
                extreme_fraction=extreme_fraction,
                extreme_factor=extreme_factor,
            )
            base_filename = instance_filename(
                quay_code=quay_code,
                week_start=week_start,
                density_percentage=100,
            )
            write_instance(
                base_instance,
                output_folders[("fix", "max-compl")] / base_filename,
            )
            write_instance(
                position_instance,
                output_folders[("pos", "max-compl")] / base_filename,
            )

            weight_profiles = generate_weight_profiles(
                ship_lengths=base_instance["ship_len"],
                quay_code=quay_code,
                week_start=week_start,
                density_percentage=100,
                random_seed=random_seed,
            )
            desired_times = desired_completion_times(
                arrival_times=base_instance["arrival_time"],
                handling_times=base_instance["handling_time"],
                n_periods=base_instance["n_periods"],
                rng=instance_rng(
                    quay_code=quay_code,
                    week_start=week_start,
                    density_percentage=100,
                    purpose="desired-completion-times",
                    random_seed=random_seed,
                ),
            )

            position_tardiness_instances = {}
            for handling_attribute, geometry_instance in (
                ("fix", base_instance),
                ("pos", position_instance),
            ):
                for weight_regime, weights in weight_profiles.items():
                    weighted_filename = instance_filename(
                        quay_code=quay_code,
                        week_start=week_start,
                        density_percentage=100,
                        weight_regime=weight_regime,
                    )
                    waiting_handling_instance = (
                        make_weighted_objective_instance(
                            instance=geometry_instance,
                            objective_function=(
                                WEIGHTED_SUM_WAITING_HANDLING
                            ),
                            weights=weights,
                        )
                    )
                    waiting_tardiness_instance = (
                        make_weighted_objective_instance(
                            instance=geometry_instance,
                            objective_function=(
                                WEIGHTED_SUM_WAITING_TARDINESS
                            ),
                            weights=weights,
                            desired_times=desired_times,
                        )
                    )
                    write_instance(
                        waiting_handling_instance,
                        output_folders[
                            (handling_attribute, "sum-wait-hand")
                        ]
                        / weighted_filename,
                    )
                    write_instance(
                        waiting_tardiness_instance,
                        output_folders[
                            (handling_attribute, "sum-wait-tard")
                        ]
                        / weighted_filename,
                    )

                    if handling_attribute == "pos":
                        position_tardiness_instances[weight_regime] = (
                            waiting_tardiness_instance
                        )

            for density_percentage in sparse_densities:
                sparse_filename = instance_filename(
                    quay_code=quay_code,
                    week_start=week_start,
                    density_percentage=density_percentage,
                )
                write_instance(
                    sparsify_instance(
                        instance=base_instance,
                        density_percentage=density_percentage,
                        permutation=permutation,
                    ),
                    output_folders[("fix", "max-compl")]
                    / sparse_filename,
                )

                for weight_regime, dense_instance in (
                    position_tardiness_instances.items()
                ):
                    sparse_weighted_filename = instance_filename(
                        quay_code=quay_code,
                        week_start=week_start,
                        density_percentage=density_percentage,
                        weight_regime=weight_regime,
                    )
                    write_instance(
                        sparsify_instance(
                            instance=dense_instance,
                            density_percentage=density_percentage,
                            permutation=permutation,
                        ),
                        output_folders[("pos", "sum-wait-tard")]
                        / sparse_weighted_filename,
                    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the Barcelona BAP instance families."
    )
    parser.add_argument(
        "--raw-data",
        type=Path,
        default=DEFAULT_RAW_DATA_PATH,
        help="Path to Barcelona_2024.csv.",
    )
    parser.add_argument(
        "--instances-root",
        type=Path,
        default=DEFAULT_INSTANCES_ROOT,
        help="Root output directory for generated instance folders.",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=RANDOM_SEED,
        help="Seed used for all reproducible random generation.",
    )
    parser.add_argument(
        "--extreme-fraction",
        type=float,
        default=EXTREME_QUAY_FRACTION,
        help="Fraction at each end of the quay receiving a penalty.",
    )
    parser.add_argument(
        "--extreme-factor",
        type=float,
        default=EXTREME_HANDLING_FACTOR,
        help="Handling-time multiplier for extreme placements.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    generate_all_instances(
        raw_data_path=arguments.raw_data,
        instances_root=arguments.instances_root,
        random_seed=arguments.random_seed,
        extreme_fraction=arguments.extreme_fraction,
        extreme_factor=arguments.extreme_factor,
    )
