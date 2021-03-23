# Copyright 2021 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


# from kfp.components import OutputPath
from typing import NamedTuple


def create_training_pipeline_custom_job(
    project: str,
    display_name: str,
    model_display_name: str,
    train_container_type: str,
    executor_image_uri: str,
    package_uri: str,
    python_module: str,
    container_image_uri: str,
    base_output_directory_prefix: str,
    prediction_image_uri: str,  # 'us-docker.pkg.dev/cloud-aiplatform/prediction/tf2-cpu.2-3:latest'
    location: str,  # "us-central1"
    api_endpoint: str,  # "us-central1-aiplatform.googleapis.com",
    data_dir: str,
    hptune_dict: str,
    # model_id: OutputPath('String'),
    # model_dispname: OutputPath('String')
) -> NamedTuple('Outputs', [('model_id', str), ('model_dispname', str)]):

  import logging
  import subprocess
  import time

  from google.cloud import aiplatform
  from google.protobuf import json_format
  from google.protobuf.struct_pb2 import Value
  from google.cloud.aiplatform_v1beta1.types import pipeline_state

  logging.getLogger().setLevel(logging.INFO)

  # The AI Platform services require regional API endpoints.
  client_options = {"api_endpoint": api_endpoint}
  # Initialize client that will be used to create and send requests.
  # This client only needs to be created once, and can be reused for multiple requests.
  client = aiplatform.gapic.PipelineServiceClient(client_options=client_options)

  if train_container_type == 'prebuilt':
    python_package_spec = {
        "executor_image_uri": executor_image_uri,
        "package_uris": [package_uri],
        "python_module": python_module,
        "args": [f"--data-dir={data_dir}",
                 f"--hptune-dict={hptune_dict}"]}
    worker_pool_spec = {
              "machine_spec": {
                  "machine_type": "n1-standard-16",
                  "accelerator_type": aiplatform.gapic.AcceleratorType.NVIDIA_TESLA_K80,
                  "accelerator_count": 2,
                  },
              "replica_count": 1,
              "python_package_spec": python_package_spec,
          }
  elif train_container_type == 'custom':
    container_spec = {
        # A working docker image can be found at gs://cloud-samples-data/ai-platform/mnist_tfrecord/custom_job
        "imageUri": container_image_uri,
        "args": [
            # AIP_MODEL_DIR is set by the service according to baseOutputDirectory.
            "--model_dir=$(AIP_MODEL_DIR)",
        ]}
    worker_pool_spec = {
              "machine_spec": {
                  "machine_type": "n1-standard-16",
                  "accelerator_type": aiplatform.gapic.AcceleratorType.NVIDIA_TESLA_K80,
                  "accelerator_count": 2,
                  },
              "replica_count": 1,
              "container_spec": container_spec,
          }
  else:
    logging.warning('unknown train_container_type; exiting')
    exit(1)

  training_task_inputs_dict = {
      "workerPoolSpecs": [
        worker_pool_spec
      ],
      "baseOutputDirectory": {
          # The GCS location for outputs must be accessible by the project's AI Platform service account.
          "output_uri_prefix": base_output_directory_prefix
      },
  }
  training_task_inputs = json_format.ParseDict(training_task_inputs_dict, Value())

  training_task_definition = "gs://google-cloud-aiplatform/schema/trainingjob/definition/custom_task_1.0.0.yaml"
  # image_uri = "gcr.io/cloud-aiplatform/prediction/tf-cpu.1-15:latest"
  # image_uri = 'us-docker.pkg.dev/cloud-aiplatform/prediction/tf2-cpu.2-3:latest'

  training_pipeline = {
      "display_name": display_name,
      "training_task_definition": training_task_definition,
      "training_task_inputs": training_task_inputs,
      "model_to_upload": {
          "display_name": model_display_name,
          "container_spec": {"image_uri": prediction_image_uri},
      },
  }
  parent = f"projects/{project}/locations/{location}"
  response = client.create_training_pipeline(
      parent=parent, training_pipeline=training_pipeline
  )
  logging.info("training pipeline request response: %s", response)

  SLEEP_INTERVAL = 100

  training_pipeline_name = response.name
  logging.info("training pipeline name: %s", training_pipeline_name)
  # Poll periodically until training completes
  while True:
    mresponse = client.get_training_pipeline(name=training_pipeline_name)
    logging.info('mresponse: %s', mresponse)
    logging.info('job state: %s', mresponse.state)
    if mresponse.state == pipeline_state.PipelineState.PIPELINE_STATE_FAILED:
      logging.warning('training pipeline failed: %s', mresponse)
      exit(1)
    if mresponse.state == pipeline_state.PipelineState.PIPELINE_STATE_SUCCEEDED:
      logging.info('training finished')
      model_name = mresponse.model_to_upload.name
      return (model_name, model_display_name)
      # # write some outputs once finished
      # model_name = mresponse.model_to_upload.name
      # logging.info('got model name: %s', model_name)
      # with open('temp.txt', "w") as outfile:
      #   outfile.write(model_name)
      # subprocess.run(['gsutil', 'cp', 'temp.txt', model_id])
      # with open('temp2.txt', "w") as outfile:
      #   outfile.write(model_display_name)
      # subprocess.run(['gsutil', 'cp', 'temp2.txt', model_dispname])
      # break
    else:
      time.sleep(SLEEP_INTERVAL)

if __name__ == '__main__':
  # create_training_pipeline_custom_job(
  #   'aju-vtests2', 'bw_sdktest2',
  #   'bw_sdktest2',
  #   'us-docker.pkg.dev/cloud-aiplatform/training/tf-gpu.2-3:latest',
  #   'gs://aju-pipelines/ucaip/training1/bw-trainer-0.1.tar.gz',
  #   'trainer.task',
  #   'gs://aju-pipelines/ucaip/test1803_sdk1',
  #   "us-central1",
  #   "us-central1-aiplatform.googleapis.com",
  # )
  import kfp
  kfp.components.func_to_container_op(create_training_pipeline_custom_job,
      output_component_file='../model_train_component.yaml',
      base_image='gcr.io/aju-vtests2/bw-aiplatform:v1')