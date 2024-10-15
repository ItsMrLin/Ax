# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

# pyre-strict
import sys
from enum import Enum, unique
from math import ceil
from typing import Any

from ax.core import ObservationFeatures
from ax.core.base_trial import STATUSES_EXPECTING_DATA
from ax.core.experiment import Experiment
from ax.core.utils import get_target_trial_index
from ax.exceptions.generation_strategy import AxGenerationException

from ax.modelbridge.generation_node import GenerationNode
from ax.utils.common.constants import Keys


@unique
class NodeInputConstructors(Enum):
    """An enum which maps to a the name of a callable method for constructing
    ``GenerationNode`` inputs.

    NOTE: The methods defined by this enum should all share identical signatures
    and reside in this file.
    """

    ALL_N = "consume_all_n"
    REPEAT_N = "repeat_arm_n"
    REMAINING_N = "remaining_n"
    TARGET_TRIAL_FIXED_FEATURES = "set_target_trial"

    def __call__(
        self,
        previous_node: GenerationNode | None,
        next_node: GenerationNode,
        gs_gen_call_kwargs: dict[str, Any],
        experiment: Experiment,
    ) -> int:
        """Defines a callable method for the Enum as all values are methods"""
        try:
            method = getattr(sys.modules[__name__], self.value)
        except AttributeError:
            raise ValueError(
                f"{self.value} is not defined as a method in "
                "``generation_node_input_constructors.py``. Please add the method "
                "to the file."
            )
        return method(
            previous_node=previous_node,
            next_node=next_node,
            gs_gen_call_kwargs=gs_gen_call_kwargs,
            experiment=experiment,
        )


@unique
class InputConstructorPurpose(Enum):
    """A simple enum to indicate the purpose of the input constructor.

    Explanation of the different purposes:
        N: Defines the logic to determine the number of arms to generate from the
           next ``GenerationNode`` given the total number of arms expected in
           this trial.
    """

    N = "n"
    FIXED_FEATURES = "fixed_features"


def set_target_trial(
    previous_node: GenerationNode | None,
    next_node: GenerationNode,
    gs_gen_call_kwargs: dict[str, Any],
    experiment: Experiment,
) -> ObservationFeatures | None:
    """Determine the target trial for the next node based on the current state of the
    ``Experiment``.

     Args:
        previous_node: The previous node in the ``GenerationStrategy``. This is the node
            that is being transition away from, and is provided for easy access to
            properties of this node.
        next_node: The next node in the ``GenerationStrategy``. This is the node that
            will leverage the inputs defined by this input constructor.
        gs_gen_call_kwargs: The kwargs passed to the ``GenerationStrategy``'s
            gen call.
        experiment: The experiment associated with this ``GenerationStrategy``.
    Returns:
        An ``ObservationFeatures`` object that defines the target trial for the next
        node.
    """
    target_trial_idx = get_target_trial_index(experiment=experiment)
    if target_trial_idx is None:
        raise AxGenerationException(
            f"Attempting to construct for input into {next_node} but no trials match "
            "the expected conditions. Often this could be due to no trials on the "
            f"experiment that are in status {STATUSES_EXPECTING_DATA} on the "
            f"experiment. The trials on this experiment are: {experiment.trials}."
        )
    return ObservationFeatures(
        parameters={},
        trial_index=target_trial_idx,
    )


def consume_all_n(
    previous_node: GenerationNode | None,
    next_node: GenerationNode,
    gs_gen_call_kwargs: dict[str, Any],
    experiment: Experiment,
) -> int:
    """Generate total requested number of arms from the next node.

    Example: Initial exploration with Sobol will generate all arms from a
    single sobol node.

    Note: If no `n` is provided to the ``GenerationStrategy`` gen call, we will use
    the default number of arms for the next node, defined as a constant `DEFAULT_N`
    in the ``GenerationStrategy`` file.

    Args:
        previous_node: The previous node in the ``GenerationStrategy``. This is the node
            that is being transition away from, and is provided for easy access to
            properties of this node.
        next_node: The next node in the ``GenerationStrategy``. This is the node that
            will leverage the inputs defined by this input constructor.
        gs_gen_call_kwargs: The kwargs passed to the ``GenerationStrategy``'s
            gen call.
        experiment: The experiment associated with this ``GenerationStrategy``.
    Returns:
        The total number of requested arms from the next node.
    """
    return (
        gs_gen_call_kwargs.get("n")
        if gs_gen_call_kwargs.get("n") is not None
        else _get_default_n(experiment=experiment, next_node=next_node)
    )


def repeat_arm_n(
    previous_node: GenerationNode | None,
    next_node: GenerationNode,
    gs_gen_call_kwargs: dict[str, Any],
    experiment: Experiment,
) -> int:
    """Generate a small percentage of arms requested to be used for repeat arms in
    the next trial.

    Note: If no `n` is provided to the ``GenerationStrategy`` gen call, we will use
    the default number of arms for the next node, defined as a constant `DEFAULT_N`
    in the ``GenerationStrategy`` file.

    Args:
        previous_node: The previous node in the ``GenerationStrategy``. This is the node
            that is being transition away from, and is provided for easy access to
            properties of this node.
        next_node: The next node in the ``GenerationStrategy``. This is the node that
            will leverage the inputs defined by this input constructor.
        gs_gen_call_kwargs: The kwargs passed to the ``GenerationStrategy``'s
            gen call.
        experiment: The experiment associated with this ``GenerationStrategy``.
    Returns:
        The number of requested arms from the next node
    """
    total_n = (
        gs_gen_call_kwargs.get("n")
        if gs_gen_call_kwargs.get("n") is not None
        else _get_default_n(experiment=experiment, next_node=next_node)
    )
    if total_n < 6:
        # if the next trial is small, we don't want to waste allocation on repeat arms
        # users can still manually add repeat arms if they want before allocation
        return 0
    elif total_n <= 10:
        return 1
    return ceil(total_n / 10)


def remaining_n(
    previous_node: GenerationNode | None,
    next_node: GenerationNode,
    gs_gen_call_kwargs: dict[str, Any],
    experiment: Experiment,
) -> int:
    """Generate the remaining number of arms requested for this trial in gs.gen().

    Note: If no `n` is provided to the ``GenerationStrategy`` gen call, we will use
    the default number of arms for the next node, defined as a constant `DEFAULT_N`
    in the ``GenerationStrategy`` file.

    Args:
        previous_node: The previous node in the ``GenerationStrategy``. This is the node
            that is being transition away from, and is provided for easy access to
            properties of this node.
        next_node: The next node in the ``GenerationStrategy``. This is the node that
            will leverage the inputs defined by this input constructor.
        gs_gen_call_kwargs: The kwargs passed to the ``GenerationStrategy``'s
            gen call.
        experiment: The experiment associated with this ``GenerationStrategy``.
    Returns:
        The number of requested arms from the next node
    """
    # TODO: @mgarrard improve this logic to be more robust
    grs_this_gen = gs_gen_call_kwargs.get("grs_this_gen", [])
    total_n = (
        gs_gen_call_kwargs.get("n")
        if gs_gen_call_kwargs.get("n") is not None
        else _get_default_n(experiment=experiment, next_node=next_node)
    )
    # if all arms have been generated, return 0
    return max(total_n - sum(len(gr.arms) for gr in grs_this_gen), 0)


# Helper methods for input constructors
def _get_default_n(experiment: Experiment, next_node: GenerationNode) -> int:
    """Get the default number of arms to generate from the next node.

    Args:
        experiment: The experiment associated with this ``GenerationStrategy``.
        next_node: The next node in the ``GenerationStrategy``. This is the node that
            will leverage the inputs defined by this input constructor.

    Returns:
        The default number of arms to generate from the next node, used if no n is
        provided to the ``GenerationStrategy``'s gen call.
    """
    total_concurrent_arms = experiment._properties.get(
        Keys.EXPERIMENT_TOTAL_CONCURRENT_ARMS.value
    )
    return (
        total_concurrent_arms
        if total_concurrent_arms is not None
        # GS default n is 1, but these input constructors are used for nodes that
        # should generate more than 1 arm per trial, default to 10
        else next_node.generation_strategy.DEFAULT_N * 10
    )
