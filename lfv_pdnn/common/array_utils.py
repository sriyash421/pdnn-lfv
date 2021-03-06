import time
import warnings

import numpy as np

from lfv_pdnn.common import common_utils


def clean_negative_weights(array, weight_id, verbose=False):
    """removes elements with negative weight.

    Args:
        array: numpy array, input array to be processed, must be numpy array
        weight_id: int, indicate which column is weight value.
        verbose: bool, optional, show more detailed message if set True.

    Returns:
        cleaned new numpy array.
    """
    # Start
    if verbose:
        print("cleaning array elements with negative weights...")
    # Clean
    # create new array for output to avoid direct operation on input array
    new = []
    for d in array:
        if d[weight_id] < 0.0:  # remove zero or negative weight row
            continue
        new.append(d)
    # Output
    out = np.array(new)
    if verbose:
        print("shape before", array.shape, "shape after", out.shape)
    return out


def clean_zero_weights(array, weight_id, verbose=False):
    """removes elements with 0 weight.

    Args:
        array: numpy array, input array to be processed, must be numpy array
        weight_id: int, indicate which column is weight value.
        verbose: bool, optional, show more detailed message if set True.

    Returns:
        cleaned new numpy array.
    """
    # Start
    if verbose:
        print("cleaning array elements with zero weights ...")
    # Clean
    # create new array for output to avoid direct operation on input array
    new = []
    for d in array:
        if d[weight_id] == 0.0:  # only remove zero weight row
            continue
        new.append(d)
    # Output
    out = np.array(new)
    if verbose:
        print("shape before", array.shape, "shape after", out.shape)
    return out


def get_cut_index(array, cut_values, cut_types):
    """Parses cuts arguments and returns cuts indexes."""
    assert len(cut_values) == len(
        cut_types
    ), "cut_values and cut_types should have same length."
    pass_index = None
    for cut_value, cut_type in zip(cut_values, cut_types):
        temp_index = get_cut_index_value(array, cut_value, cut_type)
        if pass_index is None:
            pass_index = temp_index
        else:
            pass_index = np.intersect1d(pass_index, temp_index)
    return pass_index


def get_cut_index_value(array, cut_value, cut_type):
    """Returns cut indexes based on cut_value and cut_type.

    If cut_type is "=":
        returns all indexes that have values equal to cut_value
    If cut_type is ">":
        returns all indexes that have values lager than cut_value
    If cut_type is "<":
        returns all indexes that have values smaller than cut_value

    Args:
        array_dict: numpy array
        cut_feature: str
        cut_bool: bool
    """
    # Make cuts
    if cut_type == "=":
        pass_index = np.argwhere(array == cut_value)
    elif cut_type == ">":
        pass_index = np.argwhere(array > cut_value)
    elif cut_type == "<":
        pass_index = np.argwhere(array < cut_value)
    else:
        raise ValueError("Invalid cut_type specified.")
    return pass_index.flatten()


def modify_array(
    input_array,
    remove_negative_weight=False,
    select_channel=False,
    select_mass=False,
    mass_id=None,
    mass_min=None,
    mass_max=None,
    reset_mass=False,
    reset_mass_array=None,
    reset_mass_id=None,
    norm=False,
    sumofweight=1000,
    shuffle=False,
    shuffle_seed=None,
):
    """Modifies numpy array with given setup.

    Args:
        input_array: numpy array
            Array to be modified.
        remove_negative_weight: bool, optional (default=False) 
            Whether to remove events with negative weight.
        select_channel: bool, optional (default=False) 
            Whether to select specific channel. 
            If True, channel will be selected by checking index -2
        select_mass: bool, optional (default=False)
            Whether to select elements within cerntain mass range.
            If True, mass_id/mass_min/mass_max shouldn't be None.
        mass_id: int or None, optional (default=None)
            Column index of mass id.
        mass_min: float or None, optional (default=None)
            Mass lower limit.
        mass_max: float or None, optional (default=None)
            Mass higher limit.
        reset_mass: bool, optional (default=None)
            Whether to reset mass with given array's value distribution.
            If set True, reset_mass_array/reset_mass_id shouldn't be None.
        reset_mass_array: numpy array or none, optional (default=None):
            Array used to reset input_array's mass distribution.
        reset_mass_id: int or None, optional (default=None)
            Column index of mass id to reset input_array.
        norm: bool, optional (default=False)
            Whether normalize array's weight to sumofweight.
        sumofweight: float or None, optional (default=None)
            Total normalized weight.
        shuffle: bool, optional (default=None)
            Whether to randomlize the output array.
        shuffle_seed: int or None, optional (default=None)
            Seed for randomization process.
            Set to None to use current time as seed.
            Set to a specific value to get an unchanged shuffle result.

      Returns:
          new: numpy array
              Modified numpy array.

  """
    # Modify
    new = input_array.copy()  # copy data to avoid original data operation
    if len(new) == 0:
        warnings.warn("empty input detected in modify_array, no changes will be made.")
        return new
    # select channel
    if select_channel == True:
        for ele in new:
            if ele[-2] != 1.0:
                ele[-1] = 0
    # select mass range
    if select_mass == True:
        if not common_utils.has_none([mass_id, mass_min, mass_max]):
            for ele in new:
                if ele[mass_id] < mass_min or ele[mass_id] > mass_max:
                    ele[-1] = 0
        else:
            print("missing parameters, skipping mass selection...")
    # clean array
    new = clean_zero_weights(new, -1)
    if remove_negative_weight:
        new = clean_negative_weights(new, -1)
    # reset mass
    if reset_mass == True:
        if not common_utils.has_none([reset_mass_array, reset_mass_id]):
            new = prep_mass_fast(new, reset_mass_array, mass_id=reset_mass_id)
        else:
            print("missing parameters, skipping mass reset...")
    # normalize weight
    if norm == True:
        new[:, -1] = norweight(new[:, -1], norm=sumofweight)
    # shuffle array
    if shuffle == True:
        new, _, _, _ = shuffle_and_split(
            new, np.zeros(len(new)), split_ratio=0.0, shuffle_seed=shuffle_seed
        )
    # return result
    return new


def norweight(weight_array, norm=1000):
    """Normalize given weight array to certain value

    Args:
        weight_array: numpy array
            Array to be normalized.
        norm: float (default=1000)
            Value to be normalized to.

    Returns:
        new: numpyt array
          normalized array.

    Example:
      arr has weight value saved in column -1.
      To normalize it's total weight to 1:
        arr[:, -1] = norweight(arr[:, -1], norm=1)

    """
    new = weight_array.copy()  # copy data to avoid original data operation
    total_weight = sum(new)
    frac = norm / total_weight
    new = frac * new
    return new


def prep_mass_fast(xbtrain, xstrain, mass_id=0, shuffle_seed=None):
    """Resets background mass distribution according to signal distribution

    Args:
        xbtrain: numpy array
            Background array
        xstrain: numpy array
            Siganl array
        mass_id: int (default=0)
            Column index of mass.
        shuffle_seed: int or None, optional (default=None)
            Seed for randomization process.
            Set to None to use current time as seed.
            Set to a specific value to get an unchanged shuffle result.

    Returns:
        new: numpy array
            new background array with mass distribution reset

    """
    new = reset_col(xbtrain, xstrain, col=mass_id, shuffle_seed=None)
    return new


def reset_col(reset_array, ref_array, col=0, shuffle_seed=None):
    """Resets one column in an array based on the distribution of refference."""
    if common_utils.has_none([shuffle_seed]):
        shuffle_seed = int(time.time())
    np.random.seed(shuffle_seed)
    new = reset_array.copy()
    total_events = len(new)
    sump = sum(ref_array[:, -1])
    reset_list = np.random.choice(
        ref_array[:, col], size=total_events, p=1 / sump * ref_array[:, -1]
    )
    for count, entry in enumerate(new):
        entry[col] = reset_list[count]
    return new


def shuffle_and_split(x, y, split_ratio=0.0, shuffle_seed=None):
    """Self defined function to replace train_test_split in sklearn to allow
    more flexibility.
    """
    # Check consistence of length of x, y
    if len(x) != len(y):
        raise ValueError("Length of x and y is not same.")
    array_len = len(y)
    np.random.seed(shuffle_seed)
    # get index for the first part of the splited array
    first_part_index = np.random.choice(
        range(array_len), int(array_len * 1.0 * split_ratio), replace=False
    )
    # get index for last part of the splitted array
    last_part_index = np.setdiff1d(np.array(range(array_len)), first_part_index)
    first_part_x = x[first_part_index]
    first_part_y = y[first_part_index]
    last_part_x = x[last_part_index]
    last_part_y = y[last_part_index]
    return first_part_x, last_part_x, first_part_y, last_part_y
