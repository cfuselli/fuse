import numpy as np
import awkward as ak
import straxen
import strax
import numba
from copy import deepcopy


def full_array_to_numpy(array, dtype):
    
    len_output = len(awkward_to_flat_numpy(array["x"]))

    numpy_data = np.zeros(len_output, dtype=dtype)

    for field in array.fields:
        numpy_data[field] = awkward_to_flat_numpy(array[field])
        
    return numpy_data

#WFSim functions

def make_map(map_file, fmt=None, method='WeightedNearestNeighbors'):
    """Fetch and make an instance of InterpolatingMap based on map_file
    Alternatively map_file can be a list of ["constant dummy", constant: int, shape: list]
    return an instance of  DummyMap"""

    if isinstance(map_file, list):
        assert map_file[0] == 'constant dummy', ('Alternative file input can only be '
                                                 '("constant dummy", constant: int, shape: list')
        return DummyMap(map_file[1], map_file[2])

    elif isinstance(map_file, str):
        if fmt is None:
            fmt = parse_extension(map_file)

        #log.debug(f'Initialize map interpolator for file {map_file}')
        map_data = straxen.get_resource(map_file, fmt=fmt)
        return straxen.InterpolatingMap(map_data, method=method)

    else:
        raise TypeError("Can't handle map_file except a string or a list")

def make_patternmap(map_file, fmt=None, method='WeightedNearestNeighbors', pmt_mask=None):
    """ This is special interpretation of the of previous make_map(), but designed
    for pattern map loading with provided PMT mask. This way simplifies both S1 and S2
    cases
    """
    # making tests not failing, we can probably overwrite it completel
    if isinstance(map_file, list):
        #log.warning(f'Using dummy map with pattern mask! This has no effect here!')
        assert map_file[0] == 'constant dummy', ('Alternative file input can only be '
                                                 '("constant dummy", constant: int, shape: list')
        return DummyMap(map_file[1], map_file[2])
    elif isinstance(map_file, str):
        if fmt is None:
            fmt = parse_extension(map_file)
        map_data = deepcopy(straxen.get_resource(map_file, fmt=fmt))
        # XXX: straxed deals with pointers and caches resources, it means that resources are global
        # what is bad, so we make own copy here and modify it locally
        if 'compressed' in map_data:
            compressor, dtype, shape = map_data['compressed']
            map_data['map'] = np.frombuffer(
                strax.io.COMPRESSORS[compressor]['decompress'](map_data['map']),
                dtype=dtype).reshape(*shape)
            del map_data['compressed']
        if 'quantized' in map_data:
            map_data['map'] = map_data['quantized']*map_data['map'].astype(np.float32)
            del map_data['quantized']
        if not (pmt_mask is None):
            assert (map_data['map'].shape[-1]==pmt_mask.shape[0]), "Error! Pattern map and PMT gains must have same dimensions!"
            map_data['map'][..., ~pmt_mask]=0.0
        return straxen.InterpolatingMap(map_data, method=method)
    else:
        raise TypeError("Can't handle map_file except a string or a list")


def parse_extension(name):
    """Get the extention from a file name. If zipped or tarred, can contain a dot"""
    split_name = name.split('.')
    if len(split_name) == 2:
        fmt = split_name[-1]
    elif len(split_name) > 2 and 'gz' in name:
        fmt = '.'.join(split_name[-2:])
    else:
        fmt = split_name[-1]
    #log.warning(f'Using {fmt} for unspecified {name}')
    return fmt

class DummyMap:
    """Return constant results
        the length match the length of input
        but from the second dimensions the shape is user defined input
    """
    def __init__(self, const, shape=()):
        self.const = const
        self.shape = shape

    def __call__(self, x, **kwargs):
        shape = [len(x)] + list(self.shape)
        return np.ones(shape) * self.const

    def reduce_last_dim(self):
        assert len(self.shape) >= 1, 'Need at least 1 dim to reduce further'
        const = self.const * self.shape[-1]
        shape = list(self.shape)
        shape[-1] = 1

        return DummyMap(const, shape)
    


# Epix functions

def reshape_awkward(array, offset):
    """
    Function which reshapes an array of strings or numbers according
    to a list of offsets. Only works for a single jagged layer.

    Args:
        array: Flatt array which should be jagged.
        offset: Length of subintervals


    Returns:
        res: awkward1.ArrayBuilder object.
    """
    res = ak.ArrayBuilder()
    if (array.dtype == np.int) or (array.dtype == np.float64) or (array.dtype == np.float32):
        _reshape_awkward_number(array, offset, res)
    else:
        _reshape_awkward_string(array, offset, res)
    return res.snapshot()


@numba.njit
def _reshape_awkward_number(array, offsets, res):
    """
    Function which reshapes an array of numbers according
    to a list of offsets. Only works for a single jagged layer.

    Args:
        array: Flatt array which should be jagged.
        offsets: Length of subintervals
        res: awkward1.ArrayBuilder object

    Returns: 
        res: awkward1.ArrayBuilder object
    """
    start = 0
    end = 0
    for o in offsets:
        end += o
        res.begin_list()
        for value in array[start:end]:
            res.real(value)
        res.end_list()
        start = end

def _reshape_awkward_string(array, offsets, res):
    """
    Function which reshapes an array of strings according
    to a list of offsets. Only works for a single jagged layer.

    Args:
        array: Flatt array which should be jagged.
        offsets: Length of subintervals
        res: awkward1.ArrayBuilder object

    Returns: 
        res: awkward1.ArrayBuilder object
    """
    start = 0
    end = 0
    for o in offsets:
        end += o
        res.begin_list()
        for value in array[start:end]:
            res.string(value)
        res.end_list()
        start = end

def awkward_to_flat_numpy(array):
    if len(array) == 0:
        return ak.to_numpy(array)
    return (ak.to_numpy(ak.flatten(array)))


def calc_dt(result):
    """
    Calculate dt, the time difference from the initial data in the event
    With empty check
    :param result: Including `t` field
    :return dt: Array like
    """
    if len(result) == 0:
        return np.empty(0)
    dt = result['t'] - result['t'][:, 0]
    return dt

def ak_num(array, **kwargs):
    """
    awkward.num() wrapper also for work in empty array
    :param array: Data containing nested lists to count.
    :param kwargs: keywords arguments for awkward.num().
    :return: an array of integers specifying the number of elements
        at a particular level. If array is empty, return empty.
    """
    if len(array) == 0:
        return ak.from_numpy(np.empty(0, dtype='int64'))
    return ak.num(array, **kwargs)


@numba.njit
def offset_range(offsets):
    """
    Computes range of constant event ids while in same offset. E.g.
    for an array [1], [1,2,3], [5] this function yields [0, 1, 1, 1, 2].

    Args:
        offsets (ak.array): jagged array offsets.

    Returns:
        np.array: Indicies.
    """
    res = np.zeros(np.sum(offsets), dtype=np.int32)
    i = 0
    for ind, o in enumerate(offsets):
        res[i:i+o] = ind
        i += o
    return res

@numba.jit(numba.int32(numba.int64[:], numba.int64, numba.int64, numba.int64[:, :]),
           nopython=True)
def find_intervals_below_threshold(w, threshold, holdoff, result_buffer):
    """Fills result_buffer with l, r bounds of intervals in w < threshold.
    :param w: Waveform to do hitfinding in
    :param threshold: Threshold for including an interval
    :param holdoff: Holdoff number of samples after the pulse return back down to threshold
    :param result_buffer: numpy N*2 array of ints, will be filled by function.
                          if more than N intervals are found, none past the first N will be processed.
    :returns : number of intervals processed
    Boundary indices are inclusive, i.e. the right boundary is the last index which was < threshold
    """
    result_buffer_size = len(result_buffer)
    last_index_in_w = len(w) - 1

    in_interval = False
    current_interval = 0
    current_interval_start = -1
    current_interval_end = -1

    for i, x in enumerate(w):

        if x < threshold:
            if not in_interval:
                # Start of an interval
                in_interval = True
                current_interval_start = i

            current_interval_end = i

        if ((i == last_index_in_w and in_interval) or
                (x >= threshold and i >= current_interval_end + holdoff and in_interval)):
            # End of the current interval
            in_interval = False

            # Add bounds to result buffer
            result_buffer[current_interval, 0] = current_interval_start
            result_buffer[current_interval, 1] = current_interval_end
            current_interval += 1

            if current_interval == result_buffer_size:
                result_buffer[current_interval, 1] = len(w) - 1

    n_intervals = current_interval  # No +1, as current_interval was incremented also when the last interval closed
    return n_intervals