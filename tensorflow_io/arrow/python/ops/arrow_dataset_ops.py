# Copyright 2017 The TensorFlow Authors. All Rights Reserved.
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
# ==============================================================================
"""Arrow Dataset."""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import io

import tensorflow

from tensorflow import dtypes
from tensorflow.compat.v1 import data
from tensorflow_io import _load_library
arrow_ops = _load_library('_arrow_ops.so')

if hasattr(tensorflow, "nest"):
  from tensorflow import nest # pylint: disable=ungrouped-imports
else:
  from tensorflow.python.data.util import nest # pylint: disable=ungrouped-imports


def arrow_to_tensor_type(pa_t):
  """Convert Arrow type to tuple of (Tensor dtype, shape dims).
  This function requires pyarrow to be installed.
  """
  import pyarrow as pa
  shape_dims = []  # initialize shape as scalar
  if pa.types.is_boolean(pa_t):
    tf_t = dtypes.bool
  elif pa.types.is_int8(pa_t):
    tf_t = dtypes.int8
  elif pa.types.is_int16(pa_t):
    tf_t = dtypes.int16
  elif pa.types.is_int32(pa_t):
    tf_t = dtypes.int32
  elif pa.types.is_int64(pa_t):
    tf_t = dtypes.int64
  elif pa.types.is_uint8(pa_t):
    tf_t = dtypes.uint8
  elif pa.types.is_uint16(pa_t):
    tf_t = dtypes.uint16
  elif pa.types.is_uint32(pa_t):
    tf_t = dtypes.uint32
  elif pa.types.is_uint64(pa_t):
    tf_t = dtypes.uint64
  elif pa.types.is_float16(pa_t):
    tf_t = dtypes.float16
  elif pa.types.is_float32(pa_t):
    tf_t = dtypes.float32
  elif pa.types.is_float64(pa_t):
    tf_t = dtypes.float64
  elif pa.types.is_list(pa_t):
    if pa.types.is_list(pa_t.value_type):
      raise TypeError("Nested arrays are not currently supported: " + str(pa_t))
    tf_t, shape_dims = arrow_to_tensor_type(pa_t.value_type)
    shape_dims.append(None)  # pyarrow scalar arrays can be variable length
  else:
    raise TypeError("Unsupported type in conversion from Arrow: " + str(pa_t))
  return tf_t, shape_dims


def arrow_schema_to_tensor_types(schema):
  """Convert an Arrow schema to tuple of (Tensor dtypes, TensorShapes).
  This function requires pyarrow to be installed.
  """
  type_shape_list = [arrow_to_tensor_type(field.type) for field in schema]
  tensor_types, shape_dims = zip(*type_shape_list)
  tensor_shapes = tuple(tensorflow.TensorShape(s) for s in shape_dims)
  return tensor_types, tensor_shapes


class ArrowBaseDataset(data.Dataset):
  """Base class for Arrow Datasets to provide columns used in record batches
  and corresponding output tensor types, shapes and classes.
  """

  def __init__(self, columns, output_types, output_shapes=None):
    self._columns = columns
    self._output_types = output_types
    self._output_shapes = output_shapes or \
        nest.map_structure(
            lambda _: tensorflow.TensorShape(None), self._output_types)
    super(ArrowBaseDataset, self).__init__()

  def _inputs(self):
    return []

  @property
  def output_classes(self):
    return nest.map_structure(lambda _: tensorflow.Tensor, self._output_types)

  @property
  def output_shapes(self):
    return self._output_shapes

  @property
  def output_types(self):
    return self._output_types

  @property
  def columns(self):
    return self._columns


class ArrowDataset(ArrowBaseDataset):
  """An Arrow Dataset from record batches in memory, or a Pandas DataFrame.
  """

  def __init__(self,
               columns,
               output_types,
               output_shapes=None,
               arrow_buffer=None,
               serialized_batches=None):
    """Create an ArrowDataset directly from Arrow record batches.
    This constructor requires pyarrow to be installed.

    Args:
      record_batches: An Arrow record batch or sequence of record batches
      columns: A list of column indices to be used in the Dataset
      output_types: Tensor dtypes of the output tensors
      output_shapes: TensorShapes of the output tensors or None to
                     infer partial
    """
    if arrow_buffer is None and serialized_batches is None:
      raise InvalidArgumentError(
          "Must set either buffer_address or serialized_batches argument")
    self._arrow_buffer = arrow_buffer
    if self._arrow_buffer is not None:
      address_int = arrow_buffer.address
      self._buffer_address = tensorflow.convert_to_tensor(
          address_int,
          dtype=dtypes.uint64,  # TODO
          name="buffer_address")
      self._buffer_size = tensorflow.convert_to_tensor(
          arrow_buffer.size,
          dtype=dtypes.int64,
          name="buffer_size")
      print("Python buffer: {}, size: {}".format(address_int, arrow_buffer.size))
    else:
      self._buffer_address = None
      self._buffer_size = None
    self._serialized_batches = serialized_batches
    self._columns = columns
    self._output_types = output_types
    self._output_shapes = output_shapes or \
        nest.map_structure(
            lambda _: tensorflow.TensorShape(None), self._output_types)
    super(ArrowDataset, self).__init__(columns, output_types, output_shapes)

  def _as_variant_tensor(self):
    if self._buffer_address is not None:
      return arrow_ops.arrow_dataset(
          self._buffer_address,
          self._buffer_size,
          self._columns,
          nest.flatten(self.output_types),
          nest.flatten(self.output_shapes))
    else:
      return arrow_ops.arrow_serialized_dataset(
          self._serialized_batches,
          self._columns,
          nest.flatten(self.output_types),
          nest.flatten(self.output_shapes))

  @classmethod
  def from_record_bat_ser(cls,
                          record_batches,
                          columns,
                          output_types,
                          output_shapes=None):
    import pyarrow as pa
    if isinstance(record_batches, pa.RecordBatch):
      record_batches = [record_batches]
    assert record_batches
    buf = io.BytesIO()
    writer = pa.RecordBatchFileWriter(buf, record_batches[0].schema)
    for batch in record_batches:
      writer.write_batch(batch)
    writer.close()
    serialized_batches = tensorflow.convert_to_tensor(
        buf.getvalue(),
        dtype=dtypes.string,
        name="serialized_batches")
    return cls(
        columns,
        output_types,
        output_shapes,
        serialized_batches=serialized_batches)

  @classmethod
  def from_record_batches(cls,
                          record_batches,
                          columns,
                          output_types,
                          output_shapes=None):
    import pyarrow as pa
    if isinstance(record_batches, pa.RecordBatch):
      record_batches = [record_batches]
    assert record_batches
    sink = pa.BufferOutputStream()
    writer = pa.RecordBatchFileWriter(sink, record_batches[0].schema)
    for batch in record_batches:
      writer.write_batch(batch)
    writer.close()
    return cls(columns, output_types, output_shapes, arrow_buffer=sink.getvalue())

  @classmethod
  def from_pandas(cls, df, columns=None, preserve_index=True):
    """Create an ArrowDataset from a given Pandas DataFrame. Output types
    and shapes are inferred from the Arrow schema after DataFrame conversion.
    If preserve_index is True, the DataFrame index will be the last column.
    This method requires pyarrow to be installed.

    Args:
      df: a Pandas DataFrame
      columns: Optional column indices to use, if None all are used
      preserve_index: Flag to include the DataFrame index as the last column
    """
    import pyarrow as pa
    if columns is not None:
      df = df.iloc[:, list(columns)]
    batch = pa.RecordBatch.from_pandas(df, preserve_index=preserve_index)
    columns = tuple(range(batch.num_columns))
    output_types, output_shapes = arrow_schema_to_tensor_types(batch.schema)
    return cls.from_record_batches(batch, columns, output_types, output_shapes)


class ArrowFeatherDataset(ArrowBaseDataset):
  """An Arrow Dataset for reading record batches from Arrow feather files.
  Feather is a light-weight columnar format ideal for simple writing of
  Pandas DataFrames. Pyarrow can be used for reading/writing Feather files,
  see https://arrow.apache.org/docs/python/ipc.html#feather-format
  """

  def __init__(self,
               filenames,
               columns,
               output_types,
               output_shapes=None):
    """Create an ArrowDataset from one or more Feather file names.

    Args:
      filenames: A `tf.string` tensor, Python list or scalar containing files
                 in Arrow Feather format
      columns: A list of column indices to be used in the Dataset
      output_types: Tensor dtypes of the output tensors
      output_shapes: TensorShapes of the output tensors or None to
                     infer partial
    """
    self._columns = columns
    self._output_types = output_types
    self._output_shapes = output_shapes or \
        nest.map_structure(
            lambda _: tensorflow.TensorShape(None), self._output_types)
    self._filenames = tensorflow.convert_to_tensor(
        filenames,
        dtype=dtypes.string,
        name="filenames")
    super(ArrowFeatherDataset, self).__init__(columns,
                                              output_types,
                                              output_shapes)

  def _as_variant_tensor(self):
    return arrow_ops.arrow_feather_dataset(
        self._filenames,
        self._columns,
        nest.flatten(self.output_types),
        nest.flatten(self.output_shapes))

  @classmethod
  def from_schema(cls, filenames, schema, columns=None):
    """Create an Arrow Dataset for reading record batches from Arrow feather
    files, inferring output types and shapes from the given Arrow schema.
    This method requires pyarrow to be installed.

    Args:
      filenames: A `tf.string` tensor, Python list or scalar containing files
                 in Arrow Feather format
      schema: Arrow schema defining the record batch data in the stream
      columns: A list of column indicies to use from the schema, None for all
    """
    if columns is None:
      columns = list(range(len(schema)))
    output_types, output_shapes = arrow_schema_to_tensor_types(schema)
    return cls(filenames, columns, output_types, output_shapes)


class ArrowStreamDataset(ArrowBaseDataset):
  """An Arrow Dataset for reading record batches from an input stream.
  Currently supported input streams are a socket client or stdin.
  """

  def __init__(self,
               host,
               columns,
               output_types,
               output_shapes=None):
    """Create an ArrowDataset from an input stream.

    Args:
      host: A `tf.string` tensor or Python string defining the input stream.
            For a socket client, use "<HOST_IP>:<PORT>", for stdin use "STDIN".
      columns: A list of column indices to be used in the Dataset
      output_types: Tensor dtypes of the output tensors
      output_shapes: TensorShapes of the output tensors or None to
                     infer partial
    """
    self._columns = columns
    self._output_types = output_types
    self._output_shapes = output_shapes or \
        nest.map_structure(
            lambda _: tensorflow.TensorShape(None), self._output_types)
    self._host = tensorflow.convert_to_tensor(
        host,
        dtype=dtypes.string,
        name="host")
    super(ArrowStreamDataset, self).__init__(columns,
                                             output_types,
                                             output_shapes)

  def _as_variant_tensor(self):
    return arrow_ops.arrow_stream_dataset(
        self._host, self._columns,
        nest.flatten(self.output_types),
        nest.flatten(self.output_shapes))

  @classmethod
  def from_schema(cls, host, schema, columns=None):
    """Create an Arrow Dataset from an input stream, inferring output types
    and shapes from the given Arrow schema.
    This method requires pyarrow to be installed.

    Args:
      host: A `tf.string` tensor or Python string defining the input stream.
            For a socket client, use "<HOST_IP>:<PORT>", for stdin use "STDIN".
      schema: Arrow schema defining the record batch data in the stream
      columns: A list of column indicies to use from the schema, None for all
    """
    if columns is None:
      columns = list(range(len(schema)))
    output_types, output_shapes = arrow_schema_to_tensor_types(schema)
    return cls(host, columns, output_types, output_shapes)
