#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import torch
from ax.core.search_space import SearchSpaceDigest
from ax.models.torch.botorch import BotorchModel
from ax.models.torch.botorch_moo import MultiObjectiveBotorchModel
from ax.models.torch.posterior_mean import get_PosteriorMean
from ax.utils.common.testutils import TestCase
from botorch.utils.datasets import FixedNoiseDataset


# TODO (jej): Streamline testing for a simple acquisition function.
class PosteriorMeanTest(TestCase):
    def setUp(self):
        self.tkwargs = {"device": torch.device("cpu"), "dtype": torch.double}
        self.X = torch.tensor([[1.0, 2.0, 3.0], [2.0, 3.0, 4.0]], **self.tkwargs)
        self.Y = torch.tensor([[3.0], [4.0]], **self.tkwargs)
        self.Yvar = torch.tensor([[0.0], [2.0]], **self.tkwargs)
        self.bounds = [(0.0, 1.0), (1.0, 4.0), (2.0, 5.0)]
        self.feature_names = ["x1", "x2", "x3"]
        self.objective_weights = torch.tensor([1.0], **self.tkwargs)
        self.outcome_constraints = (
            torch.tensor([[1.0]], **self.tkwargs),
            torch.tensor([[5.0]], **self.tkwargs),
        )

    def test_GetPosteriorMean(self):

        model = BotorchModel(acqf_constructor=get_PosteriorMean)
        dataset = FixedNoiseDataset(X=self.X, Y=self.Y, Yvar=self.Yvar)
        model.fit(
            datasets=[dataset],
            metric_names=["y"],
            search_space_digest=SearchSpaceDigest(
                feature_names=self.feature_names,
                bounds=self.bounds,
            ),
        )

        # test model.gen() with no outcome_constraints. Analytic.
        new_X_dummy = torch.rand(1, 1, 3, **self.tkwargs)
        gen_results = model.gen(
            n=1,
            bounds=self.bounds,
            objective_weights=self.objective_weights,
            linear_constraints=None,
        )
        self.assertTrue(
            torch.equal(gen_results.weights, torch.ones(1, dtype=self.tkwargs["dtype"]))
        )

        # test model.gen() works with outcome_constraints. qSimpleRegret.
        new_X_dummy = torch.rand(1, 1, 3, **self.tkwargs)
        model.gen(
            n=1,
            bounds=self.bounds,
            objective_weights=self.objective_weights,
            outcome_constraints=self.outcome_constraints,
            linear_constraints=None,
        )

        # test model.gen() works with chebyshev scalarization.
        model = MultiObjectiveBotorchModel(acqf_constructor=get_PosteriorMean)
        model.fit(
            datasets=[dataset, dataset],
            metric_names=["m1", "m2"],
            search_space_digest=SearchSpaceDigest(
                feature_names=self.feature_names,
                bounds=self.bounds,
            ),
        )
        new_X_dummy = torch.rand(1, 1, 3, **self.tkwargs)
        model.gen(
            n=1,
            bounds=self.bounds,
            objective_weights=torch.ones(2, **self.tkwargs),
            outcome_constraints=(
                torch.tensor([[1.0, 0.0]], **self.tkwargs),
                torch.tensor([[5.0]], **self.tkwargs),
            ),
            objective_thresholds=torch.zeros(2, **self.tkwargs),
            linear_constraints=None,
            model_gen_options={
                "acquisition_function_kwargs": {"chebyshev_scalarization": True}
            },
        )

        # ValueError with empty X_Observed
        with self.assertRaises(ValueError):
            get_PosteriorMean(
                model=model, objective_weights=self.objective_weights, X_observed=None
            )

        # test model.predict()
        new_X_dummy = torch.rand(1, 1, 3, **self.tkwargs)
        model.predict(new_X_dummy)
