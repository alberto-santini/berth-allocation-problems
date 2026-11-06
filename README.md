## Instances, Best Known Solutions and Models for Berth Allocation Problems

This repository contains instances and best known solutions for Berth Allocation Problems.
At the present moment, it contains data for problems with the following characteristics:

* Temporal aspect: dynamic (not all ships are available at the beginning of the time horizon).
* Spatial aspect: hybrid (some ship occupies more than one berth, but no ship occupies less than one berth).
* Handling aspect: fixed (the ship handling time depends on the ship but not on the assigned berth) or dynamic (the ship handling time depends on both the ship and the assigned berth).
* Objective function:
    * Bottleneck objectives: makespan (the completion time of the last ship).
    * Cumulative objectives: sum of the completion times, or weighted sum of waiting and handling times, or weighted sum of waiting times and tardiness.

These problem variants are denoted as follows in the notation introuced in: Bierwirth, Christian and Frank Meisel (2015). “A follow-up survey of berth allocation and quay crane scheduling problems in container terminals”. In: European Journal of Operational Research 244, pp. 675–689.

* For bottleneck objectives: `hyb|dyn|fix|max(compl)` and `hyb|dyn|pos|max(compl)`.
* For cumulative objectives:
    * For the sum of completion times objective: `hyb|dyn|fix|sum(compl)` and `hyb|dyn|pos|sum(compl)`.
    * For the weighted sum of waiting and handling times: `hyb|dyn|fix|sum(w(wait+hand))` and `hyb|dyn|pos|sum(w(wait+hand))`.
    * For the weighted sum of waiting times and tardiness: `hyb|dyn|fix|sum(w(wait+tard))` and `hyb|dyn|pos|sum(w(wait+tard))`.

### Instances

The instances were created starting from data made available by the [Port of Barcelona](https://opendata.portdebarcelona.cat/), Spain.
We used data relative to quays 24B (APM Terminals) and 36A (Barcelona Europe South Terminal) and describing container ship movements during 2024.
Instances are in folder `instances/`.

* Instances in subfolder `hyb_dyn_fix_max-compl` can be used for both objective functions `max(compl)` and `sum(compl)`, despite containing `max-compl` only in the folder name.
* Instances in subfolder `hyb_dyn_pos_max-compl` can be used for both objective functions `max(compl)` and `sum(compl)`, despite containing `max-compl` only in the folder name.

The file names are:

* For instances in subfolders `hyb_dyn_fix_max-compl` and `hyb_dyn_pos_max-compl`: format `bcn_<quay>_<startweek>_<retained>.json`, where `<quay>` is either 24B or 36A, `<startweek>` refers to the first week of the year 2024 included in the data, and `<retained>` is the percentage of ships retained (lower values correspond to sparser instances). For `hyb_dyn_pos_max-compl`, `<retained>` is always 100.
* For instances in the other subfolders: format `bcn_<quay>_<startweek>_<retained>_<weights>.json`, where `<weights>` defines one of three methods to generate the ship weights (described in the paper). For these instances, `<retained>` is always 100.

In all cases, to avoid inconsistencies with ships starting service in 2023 and ending it in 2024 or starting in 2024 and ending in 2025, we do not use the first and last week of the year and `<startweek>` goes from 2 to 50.

#### Instance format

The instances are in Json format, with the following structure:

* `n_ships`: number of ships arriving over the time horizon.
* `n_berths`: number of available berths.
* `n_periods`: number of periods in the time horizon. Solvers might not use this information. It is expressed in the same unit of measure as the arrival and handling times.
* `berth_len`: an array with one entry per berth. It is the berth length, expressed in the same unit of measure as the ship length (see below).
* `arrival_time`: an array with one entry per ship. It is the ship arrival time, expressed in the same unit of measure as the time horizon length (see above) and the handling times (see below).
* `handling_time`:
    * For instances with `fix` handling attribute, it is an array with one entry per ship. It is the ship handling time, i.e., the time necessary for loading and unloading operations. It is expressed in the same unit of measure as the time horizon length and the arrival time (see above).
    * For instances with `pos` handling attribute, it is an array of arrays. The outer array has one entry per ship; the second array has one entry per berth.
* `ship_len`: an array with one entry per ship. It is the ship length, expressed in the same unit of measure as the berth length (see above).

For objective functions that involve weighted sums, there is an additional field:

* `ship_importance`: an array with one entry per ship. It is the objective function weight associated with the given ship.

For objective functions that involve the tardiness, there is an additional field:

* `desired_completion_time`: an array with one entry per ship. It is the desired period by when the ship handling should be complete. Completing a ship handling after this period causes it to have a positive tardiness value. It is expressed in the same unit of measure as the time horizon length and the handling times (see above).

#### Instance generator

The instance generator and the input files used to create the instances are in folder `generator`.
They can be used to create different instance sets startgin from the 2024 Port of Barcelona data.

### Best known solutions

Best known solutions (BKS) are available in folder `bks`.
There is one BKS for each instance, in Json format, with the following structure:

* `solver`: comma-separated list of solvers that found the given best known primal feasible solution within a one-hour time limit. Valid values are "s", "ti", "rp", "pa", "gspp", which indicate five formulations from the literature; "bapb", indicating a method based on a transformation into the maximum unweighted independent set problem for objective function `max(compl)`; "bapc", indicating a method based on a transformation into the maximum weighted independent set problem for the other objective functions. These methods are described in a [recent preprint](https://santini.in/files/papers/santini-2026.pdf).
* `primal_bound`: objective value of the best known primal feasible solution. If the instance was not solved to optimality, this is a strict upper bound on the optimal solution value.
* `dual_bound`: tightest known dual bound for the objective value of the instance.
* `optimal`: `true` if the best known solution is provably optimal and `false` otherwise.
* `ships`: list describing when and where ships berth in the given primal feasible solution. Each element of the list contains some fields starting with `data_`. This is data that can be find directly in the instance file (ship id, ship length, arrival time, handling time) and does not influence the solution. By contrast, the `mooring_time` and `mooring_berth` fields describe in which period and at which berth the leftmost end of the ship berthed. They constitute the main information provided in the solution.

New BKS can be submitted in the same format by [contacting the author](mailto:alberto.santini@upf.edu).

### Citation

You can cite this repository via Zenodo:

```bib
@misc{bap_github,
    title={Instances and Best Known Solutions for Berth Allocation Problems},
    author={Santini, Alberto},
    date={2025-11-20},
    howpublished={Github repository},
    doi={10.5281/zenodo.17665596},
    url={https://github.com/alberto-santini/berth-allocation-problems/}
}
```

The repository was introduced in this paper:

```bib
@online{bap_sgcp,
    title={Solving Berth Allocation Problems via Stable Sets},
    author={Santini, Alberto},
    url={https://santini.in/files/papers/santini-2026.pdf}
}
```

### License

The code in folder `generator` is provided under the GNU General Public License v3.
See the `LICENSE` file.
