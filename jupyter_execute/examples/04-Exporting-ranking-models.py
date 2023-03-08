#!/usr/bin/env python
# coding: utf-8

# In[1]:


# Copyright 2021 NVIDIA Corporation. All Rights Reserved.
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
# ================================

# Each user is responsible for checking the content of datasets and the
# applicable licenses and determining if suitable for the intended use.


# <img src="https://developer.download.nvidia.com/notebooks/dlsw-notebooks/merlin_models_04-exporting-ranking-models/nvidia_logo.png" style="width: 90px; float: right;">
# 
# # Exporting Ranking Models
# 
# This notebook is created using the latest stable [merlin-tensorflow](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/merlin/containers/merlin-tensorflow/tags) container. 
# 
# In this example notebook we demonstrate how to export (save) NVTabular `workflow` and a `ranking model` for model deployment with [Merlin Systems](https://github.com/NVIDIA-Merlin/systems) library. 
# 
# Learning Objectives:
# 
# - Export NVTabular workflow for model deployment
# - Export TensorFlow DLRM model for model deployment
# 
# We will follow the steps below:
# - Prepare the data with NVTabular and export NVTabular workflow
# - Train a DLRM model with Merlin Models and export the trained model

# ## Importing Libraries

# Let's start with importing the libraries that we'll use in this notebook.

# In[2]:


import os

import nvtabular as nvt
from nvtabular.ops import *

from merlin.models.utils.example_utils import workflow_fit_transform
from merlin.schema.tags import Tags

import merlin.models.tf as mm
from merlin.io.dataset import Dataset
import tensorflow as tf


# ## Feature Engineering with NVTabular

# We use the synthetic train and test datasets generated by mimicking the real [Ali-CCP: Alibaba Click and Conversion Prediction](https://tianchi.aliyun.com/dataset/dataDetail?dataId=408#1) dataset to build our recommender system ranking models. 
# 
# If you would like to use real Ali-CCP dataset instead, you can download the training and test datasets on [tianchi.aliyun.com](https://tianchi.aliyun.com/dataset/dataDetail?dataId=408#1). You can then use [get_aliccp()](https://github.com/NVIDIA-Merlin/models/blob/main/merlin/datasets/ecommerce/aliccp/dataset.py#L43) function to curate the raw csv files and save them as parquet files.

# In[3]:


from merlin.datasets.synthetic import generate_data

DATA_FOLDER = os.environ.get("DATA_FOLDER", "workspace/data/")
NUM_ROWS = os.environ.get("NUM_ROWS", 1000000)
SYNTHETIC_DATA = eval(os.environ.get("SYNTHETIC_DATA", "True"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", 512))

if SYNTHETIC_DATA:
    train, valid = generate_data("aliccp-raw", int(NUM_ROWS), set_sizes=(0.7, 0.3))
    # save the datasets as parquet files
    train.to_ddf().to_parquet(os.path.join(DATA_FOLDER, "train"))
    valid.to_ddf().to_parquet(os.path.join(DATA_FOLDER, "valid"))


# Let's define our input and output paths.

# In[4]:


train_path = os.path.join(DATA_FOLDER, "train", "*.parquet")
valid_path = os.path.join(DATA_FOLDER, "valid", "*.parquet")
output_path = os.path.join(DATA_FOLDER, "processed")


# After we execute `fit()` and `transform()` functions on the raw dataset applying the operators defined in the NVTabular workflow pipeline below, the processed parquet files are saved to `output_path`.

# In[5]:


get_ipython().run_cell_magic('time', '', 'category_temp_directory = os.path.join(DATA_FOLDER, "categories")\nuser_id = ["user_id"] >> Categorify(out_path=category_temp_directory) >> TagAsUserID()\nitem_id = ["item_id"] >> Categorify(out_path=category_temp_directory) >> TagAsItemID()\ntargets = ["click"] >> AddMetadata(tags=[Tags.BINARY_CLASSIFICATION, "target"])\n\nitem_features = ["item_category", "item_shop", "item_brand"] >> Categorify(out_path=category_temp_directory) >> TagAsItemFeatures()\n\nuser_features = (\n    [\n        "user_shops",\n        "user_profile",\n        "user_group",\n        "user_gender",\n        "user_age",\n        "user_consumption_2",\n        "user_is_occupied",\n        "user_geography",\n        "user_intentions",\n        "user_brands",\n        "user_categories",\n    ]\n    >> Categorify(out_path=category_temp_directory)\n    >> TagAsUserFeatures()\n)\n\noutputs = user_id + item_id + item_features + user_features + targets\n\nworkflow = nvt.Workflow(outputs)\n\ntrain_dataset = nvt.Dataset(train_path)\nvalid_dataset = nvt.Dataset(valid_path)\n\nworkflow.fit(train_dataset)\nworkflow.transform(train_dataset).to_parquet(output_path=output_path + "/train/")\nworkflow.transform(valid_dataset).to_parquet(output_path=output_path + "/valid/")\n')


# We save NVTabular `workflow` model in the current working directory.

# In[6]:


workflow.save(os.path.join(DATA_FOLDER, "workflow"))


# Let's check out our saved workflow model folder.

# In[7]:


get_ipython().system('pip install seedir')


# In[8]:


import seedir as sd

sd.seedir(
    DATA_FOLDER,
    style="lines",
    itemlimit=10,
    depthlimit=3,
    exclude_folders=".ipynb_checkpoints",
    sort=True,
)


# ## Build and Train a DLRM model

# In this example, we build, train, and export a Deep Learning Recommendation Model [(DLRM)](https://arxiv.org/abs/1906.00091) architecture. To learn more about how to train different deep learning models, how easily transition from one model to another and the seamless integration between data preparation and model training visit [03-Exploring-different-models.ipynb](https://github.com/NVIDIA-Merlin/models/blob/main/examples/03-Exploring-different-models.ipynb) notebook.

# NVTabular workflow above exports a schema file, schema.pbtxt, of our processed dataset. To learn more about the schema object, schema file  and `tags`, you can explore [02-Merlin-Models-and-NVTabular-integration.ipynb](02-Merlin-Models-and-NVTabular-integration.ipynb).

# In[9]:


# define train and valid dataset objects
train = Dataset(os.path.join(output_path, "train", "*.parquet"))
valid = Dataset(os.path.join(output_path, "valid", "*.parquet"))

# define schema object
schema = train.schema


# In[10]:


target_column = schema.select_by_tag(Tags.TARGET).column_names[0]
target_column


# In[11]:


model = mm.DLRMModel(
    schema,
    embedding_dim=64,
    bottom_block=mm.MLPBlock([128, 64]),
    top_block=mm.MLPBlock([128, 64, 32]),
    prediction_tasks=mm.BinaryOutput(target_column),
)


# In[12]:


get_ipython().run_cell_magic('time', '', '\nmodel.compile("adam", run_eagerly=False, metrics=[tf.keras.metrics.AUC()])\nmodel.fit(train, validation_data=valid, batch_size=BATCH_SIZE)\n')


# ### Save model

# The last step of machine learning (ML)/deep learning (DL) pipeline is to deploy the ETL workflow and saved model into production. In the production setting, we want to transform the input data as done during training (ETL). We need to apply the same mean/std for continuous features and use the same categorical mapping to convert the categories to continuous integer before we use the DL model for a prediction. Therefore, we deploy the NVTabular workflow with the Tensorflow model as an ensemble model to Triton Inference using [Merlin Systems](https://github.com/NVIDIA-Merlin/systems) library very easily. The ensemble model guarantees that the same transformation is applied to the raw inputs.
# 
# Let's save our DLRM model.

# In[13]:


model.save(os.path.join(DATA_FOLDER, "dlrm"))


# We have NVTabular wokflow  and DLRM model exported, now it is time to move on to the next step: model deployment with [Merlin Systems](https://github.com/NVIDIA-Merlin/systems).

# ### Deploying the model with Merlin Systems

# We trained and exported our ranking model and NVTabular workflow. In the next step, we will learn how to deploy our trained DLRM model into [Triton Inference Server](https://github.com/triton-inference-server/server) with [Merlin Systems](https://github.com/NVIDIA-Merlin/systems) library. NVIDIA Triton Inference Server (TIS) simplifies the deployment of AI models at scale in production. TIS provides a cloud and edge inferencing solution optimized for both CPUs and GPUs. It supports a number of different machine learning frameworks such as TensorFlow and PyTorch.
# 
# For the next step, visit [Merlin Systems](https://github.com/NVIDIA-Merlin/systems) library and execute [Serving-Ranking-Models-With-Merlin-Systems](https://github.com/NVIDIA-Merlin/systems/blob/main/examples/Serving-Ranking-Models-With-Merlin-Systems.ipynb) notebook to deploy our saved DLRM and NVTabular workflow models as an ensemble to TIS and obtain prediction results for a qiven request. In doing so, you need to mount the saved DLRM and NVTabular workflow to the inference container following the instructions in the [README.md](https://github.com/NVIDIA-Merlin/systems/blob/main/examples/README.md).
