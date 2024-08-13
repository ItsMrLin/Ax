# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

# pyre-strict

from typing import Any, Callable, Optional

import numpy as np
from ax.core import Arm, GeneratorRun
from ax.core.experiment import Experiment
from ax.core.parameter import RangeParameter
from ax.core.types import TEvaluationOutcome, TParameterization
from ax.service.utils.instantiation import InstantiationBase
from ax.utils.common.constants import Keys
from ax.utils.common.typeutils import checked_cast

# from ExperimentType in ae/lazarus/fb/utils/if/ae.thrift
PBO_EXPERIMENT_TYPE: str = "PREFERENCE_LEARNING"
PE_EXPERIMENT_TYPE: str = "PREFERENCE_EXPLORATION"


def sum_utility(parameters: TParameterization) -> float:
    """Test utility function that sums over parameter values"""
    values = [checked_cast(float, v) for v in parameters.values()]
    return sum(values)


def pairwise_pref_metric_eval(
    parameters: dict[str, TParameterization],
    utility_func: Callable[[TParameterization], float] = sum_utility,
) -> dict[str, TEvaluationOutcome]:
    """evaluating pairwise comparisons using utility_func"""
    assert len(parameters.keys()) == 2
    arm1, arm2 = list(parameters.keys())
    arm1_sum, arm2_sum = sum_utility(parameters[arm1]), sum_utility(parameters[arm2])
    is_arm1_preferred = int(arm1_sum - arm2_sum > 0)
    return {
        arm1: {Keys.PAIRWISE_PREFERENCE_QUERY.value: is_arm1_preferred},
        arm2: {Keys.PAIRWISE_PREFERENCE_QUERY.value: 1 - is_arm1_preferred},
    }


def _metric_name_to_value(metric_name: str, metric_names: list[str]) -> float:
    i = sorted(metric_names).index(metric_name)
    return (i + 1) * 1000.0 + np.random.standard_normal()


def experimental_metric_eval(
    parameters: dict[str, Any], metric_names: list[str]
) -> dict[str, Any]:
    """evaluating experimental metrics

    Args:
        parameters: Dict of arm name to parameterization
        metric_names: List of metric names

    Returns:
        Dict of arm name to metric name to (mean, sem)
    """
    sorted_metric_names = sorted(metric_names)

    return {
        arm_name: {
            # metric_name: (mean, sem)
            metric_name: (
                _metric_name_to_value(metric_name, metric_names),
                10.0,
            )
            for i, metric_name in enumerate(sorted_metric_names)
        }
        for arm_name, param_dict in parameters.items()
    }


def get_pbo_experiment(
    num_parameters: int = 2,
    num_experimental_metrics: int = 3,
    parameter_names: Optional[list[str]] = None,
    tracking_metric_names: Optional[list[str]] = None,
    num_experimental_trials: int = 3,
    num_preference_trials: int = 3,
    num_preference_trials_w_repeated_arm: int = 5,
    include_sq: bool = True,
    partial_data: bool = False,
    unbounded_search_space: bool = False,
) -> Experiment:
    """Create synthetic preferential BO experiment"""
    if tracking_metric_names is None:
        tracking_metric_names = [
            f"metric{i}" for i in range(1, num_experimental_metrics + 1)
        ]
    else:
        assert len(tracking_metric_names) == num_experimental_metrics

    if parameter_names is None:
        parameter_names = [f"x{i}" for i in range(1, num_parameters + 1)]
    else:
        assert len(parameter_names) == num_parameters

    sq = {param_name: 0.0 for param_name in parameter_names} if include_sq else None

    parameters = [
        {
            "name": param_name,
            "type": "range",
            # make the default search space non-unit for better clarity in testing
            "bounds": [10.0, 30.0] if not unbounded_search_space else [-1e9, 1e9],
        }
        for param_name in parameter_names
    ]

    has_preference_query = (
        num_preference_trials > 0 or num_preference_trials_w_repeated_arm > 0
    )

    if has_preference_query:
        objectives = {Keys.PAIRWISE_PREFERENCE_QUERY.value: "maximize"}
    elif len(tracking_metric_names) > 0:
        objectives = {tracking_metric_names[0]: "maximize"}
    else:
        objectives = None

    experiment = InstantiationBase.make_experiment(
        name="pref_experiment",
        # pyre-ignore: Incompatible parameter type [6]
        parameters=parameters,
        objectives=objectives,
        tracking_metric_names=tracking_metric_names,
        is_test=True,
        # pyre-ignore: Incompatible parameter type [6]
        status_quo=sq,
    )

    # Adding arms with experimental metrics
    for _ in range(num_experimental_trials):
        arm = {}
        for param_name, param in experiment.search_space.parameters.items():
            lb = checked_cast(RangeParameter, param).lower
            ub = checked_cast(RangeParameter, param).upper
            arm[param_name] = np.random.uniform(low=lb, high=ub)
        gr = (
            # pyre-ignore: Incompatible parameter type [6]
            GeneratorRun([Arm(arm), Arm(sq)])
            if include_sq
            else GeneratorRun([Arm(arm)])
        )
        trial = experiment.new_batch_trial(generator_run=gr)
        raw_data = experimental_metric_eval(
            parameters={a.name: a.parameters for a in trial.arms},
            metric_names=tracking_metric_names,
        )
        # create incomplete data by dropping the first metric
        if partial_data:
            for v in raw_data.values():
                del v[tracking_metric_names[-1]]
        trial.attach_batch_trial_data(raw_data=raw_data)
        trial.mark_running(no_runner_required=True)
        trial.mark_completed()

    # Adding arms with preferential queries
    for _ in range(num_preference_trials):
        arms = []
        for _ in range(2):
            param_dict = {}
            for param_name, p in experiment.search_space.parameters.items():
                lb, ub = (
                    checked_cast(RangeParameter, p).lower,
                    checked_cast(RangeParameter, p).upper,
                )
                # if this experiment used as PE experiment
                if unbounded_search_space:
                    # matching how metrics are generated in experimental_metric_eval
                    param_dict[param_name] = _metric_name_to_value(
                        metric_name=param_name, metric_names=parameter_names
                    )
                else:
                    param_dict[param_name] = np.random.uniform(low=lb, high=ub)
            arms.append(Arm(parameters=param_dict))
        gr = GeneratorRun(arms)

        trial = experiment.new_batch_trial(generator_run=gr)
        trial.attach_batch_trial_data(
            raw_data=pairwise_pref_metric_eval(
                parameters={a.name: a.parameters for a in trial.arms}
            )
        )
        trial.mark_running(no_runner_required=True)
        trial.mark_completed()

    # Adding preferential queries using previously evaluated arms
    for _ in range(num_preference_trials_w_repeated_arm):
        arms = np.random.choice(
            list(experiment.arms_by_name.values()), 2, replace=False
        )
        trial = experiment.new_batch_trial()
        trial.add_arms_and_weights(arms=arms)
        trial.attach_batch_trial_data(
            raw_data=pairwise_pref_metric_eval(
                parameters={a.name: a.parameters for a in trial.arms}
            )
        )
        trial.mark_running(no_runner_required=True)
        trial.mark_completed()

    return experiment
