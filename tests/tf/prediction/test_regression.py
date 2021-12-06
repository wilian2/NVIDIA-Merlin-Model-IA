#
# Copyright (c) 2021, NVIDIA CORPORATION.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import pytest

from merlin_models.data.synthetic import SyntheticData

tf = pytest.importorskip("tensorflow")
ml = pytest.importorskip("merlin_models.tf")
test_utils = pytest.importorskip("merlin_models.tf.utils.testing_utils")

targets = {"target": tf.cast(tf.random.uniform((100,), maxval=2, dtype=tf.int32), tf.float32)}


def test_regression_head(testing_data: SyntheticData):
    from merlin_models.tf.utils import testing_utils

    body = ml.inputs(testing_data.schema).connect(ml.MLPBlock([64]))
    model = body.connect(ml.RegressionTask("target"))

    testing_utils.assert_loss_and_metrics_are_valid(model, (testing_data.tf_tensor_dict, targets))


def test_serialization_regression_head(testing_data: SyntheticData):
    from merlin_models.tf.utils import testing_utils

    body = ml.inputs(testing_data.schema).connect(ml.MLPBlock([64]))
    model = body.connect(ml.RegressionTask("target"))

    copy_model = test_utils.assert_serialization(model)
    testing_utils.assert_loss_and_metrics_are_valid(
        copy_model, (testing_data.tf_tensor_dict, targets)
    )
