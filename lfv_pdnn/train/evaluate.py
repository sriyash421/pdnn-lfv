# -*- coding: utf-8 -*-
"""Functions for making plots"""

import copy
import csv
import json
import math
import warnings

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
from matplotlib.ticker import NullFormatter
from sklearn.metrics import auc, roc_auc_score, roc_curve

import ROOT
from HEPTools.plot_utils import plot_utils, th1_tools
from lfv_pdnn.common import array_utils, common_utils
from lfv_pdnn.data_io import feed_box, get_arrays
from lfv_pdnn.train import train_utils


def calculate_auc(xs, xb, model, shuffle_col=None, rm_last_two=False):
    """Returns auc of given sig/bkg array."""
    x_plot, y_plot, y_pred = process_array(
        xs, xb, model, shuffle_col=shuffle_col, rm_last_two=rm_last_two
    )
    fpr_dm, tpr_dm, _ = roc_curve(y_plot, y_pred, sample_weight=x_plot[:, -1])
    # Calculate auc and return
    auc_value = auc(fpr_dm, tpr_dm)
    return auc_value


def get_significances(model_wrapper, significance_algo="asimov"):
    """Gets significances scan arrays.
    
    Return:
        Tuple of 4 arrays: (
            threshold array,
            significances,
            sig_total_weight_above_threshold,
            bkg_total_weight_above_threshold,
            )
    
    """
    feedbox = model_wrapper.feedbox
    model_meta = model_wrapper.model_meta
    # prepare signal
    sig_key = model_meta["sig_key"]
    sig_arr_temp = feedbox.get_array("xs", "raw", array_key=sig_key)
    sig_arr_temp[:, 0:-2] = train_utils.norarray(
        sig_arr_temp[:, 0:-2],
        average=np.array(model_meta["norm_average"]),
        variance=np.array(model_meta["norm_variance"]),
    )
    sig_selected_arr = train_utils.get_valid_feature(sig_arr_temp)
    sig_predictions = model_wrapper.get_model().predict(sig_selected_arr)
    sig_predictions_weights = np.reshape(
        feedbox.get_array("xs", "reshape", array_key=sig_key)[:, -1], (-1, 1)
    )
    # prepare background
    bkg_key = model_meta["bkg_key"]
    bkg_arr_temp = feedbox.get_array("xb", "raw", array_key=bkg_key)
    bkg_arr_temp[:, 0:-2] = train_utils.norarray(
        bkg_arr_temp[:, 0:-2],
        average=np.array(model_meta["norm_average"]),
        variance=np.array(model_meta["norm_variance"]),
    )
    bkg_selected_arr = train_utils.get_valid_feature(bkg_arr_temp)
    bkg_predictions = model_wrapper.get_model().predict(bkg_selected_arr)
    bkg_predictions_weights = np.reshape(
        feedbox.get_array("xb", "reshape", array_key=bkg_key)[:, -1], (-1, 1)
    )
    # prepare thresholds
    bin_array = np.array(range(-1000, 1000))
    thresholds = 1.0 / (1.0 + 1.0 / np.exp(bin_array * 0.02))
    thresholds = np.insert(thresholds, 0, 0)
    # scan
    significances = []
    plot_thresholds = []
    sig_above_threshold = []
    bkg_above_threshold = []
    total_sig_weight = np.sum(sig_predictions_weights)
    total_bkg_weight = np.sum(bkg_predictions_weights)
    for dnn_cut in thresholds:
        sig_ids_passed = sig_predictions > dnn_cut
        total_sig_weights_passed = np.sum(sig_predictions_weights[sig_ids_passed])
        bkg_ids_passed = bkg_predictions > dnn_cut
        total_bkg_weights_passed = np.sum(bkg_predictions_weights[bkg_ids_passed])
        if total_bkg_weights_passed > 0 and total_sig_weights_passed > 0:
            plot_thresholds.append(dnn_cut)
            current_significance = train_utils.calculate_significance(
                total_sig_weights_passed,
                total_bkg_weights_passed,
                sig_total=total_sig_weight,
                bkg_total=total_bkg_weight,
                algo=significance_algo,
            )
            # current_significance = total_sig_weights_passed / total_bkg_weights_passed
            significances.append(current_significance)
            sig_above_threshold.append(total_sig_weights_passed)
            bkg_above_threshold.append(total_bkg_weights_passed)
    total_sig_weight = np.sum(sig_predictions_weights)
    total_bkg_weight = np.sum(bkg_predictions_weights)
    return (plot_thresholds, significances, sig_above_threshold, bkg_above_threshold)


def plot_accuracy(ax: plt.axes, accuracy_list: list, val_accuracy_list: list) -> None:
    """Plots accuracy vs training epoch."""
    print("Plotting accuracy curve.")
    # Plot
    ax.plot(accuracy_list)
    ax.plot(val_accuracy_list)
    # Config
    ax.set_title("model accuracy")
    ax.set_ylabel("accuracy")
    # ax.set_ylim((0, 1))
    ax.set_xlabel("epoch")
    ax.legend(["train", "val"], loc="lower left")
    ax.grid()


def plot_auc_text(ax, titles, auc_values):
    """Plots auc information on roc curve."""
    auc_text = "auc values:\n"
    for (title, auc_value) in zip(titles, auc_values):
        auc_text = auc_text + title + ": " + str(auc_value) + "\n"
    auc_text = auc_text[:-1]
    props = dict(boxstyle="round", facecolor="white", alpha=0.3)
    ax.text(
        0.5,
        0.6,
        auc_text,
        transform=ax.transAxes,
        fontsize=10,
        verticalalignment="top",
        bbox=props,
    )


def plot_correlation_matrix(ax, corr_matrix_dict, matrix_key="bkg"):
    # Get matrix
    corr_matrix = corr_matrix_dict[matrix_key]
    # Generate a mask for the upper triangle
    mask = np.triu(np.ones_like(corr_matrix, dtype=np.bool))
    # Generate a custom diverging colormap
    cmap = sns.diverging_palette(220, 10, as_cmap=True)
    # Draw the heatmap with the mask and correct aspect ratio
    sns.heatmap(
        corr_matrix,
        mask=mask,
        cmap=cmap,
        vmax=0.3,
        center=0,
        square=True,
        linewidths=0.5,
        cbar_kws={"shrink": 0.5},
        ax=ax,
    )


def plot_feature_importance(ax, model_wrapper, log=True, max_feature=16):
    """Calculates importance of features and sort the feature.

    Definition of feature importance used here can be found in:
    https://christophm.github.io/interpretable-ml-book/feature-importance.html#feature-importance-data

    """
    print("Plotting feature importance.")
    # Prepare
    model = model_wrapper.get_model()
    feedbox = model_wrapper.feedbox
    num_feature = len(feedbox.selected_features)
    selected_feature_names = np.array(feedbox.selected_features)
    feature_importance = np.zeros(num_feature)
    (_, _, _, _, _, xs_test, _, xb_test,) = feedbox.get_train_test_arrays(
        sig_key=model_wrapper.model_meta["sig_key"],
        bkg_key=model_wrapper.model_meta["bkg_key"],
        reset_mass=False,
        use_selected=False,
    )
    xs = xs_test
    xb = xb_test
    base_auc = calculate_auc(xs, xb, model, rm_last_two=True)
    print("base auc:", base_auc)
    # Calculate importance
    for num, feature_name in enumerate(selected_feature_names):
        current_auc = calculate_auc(xs, xb, model, shuffle_col=num, rm_last_two=True)
        feature_importance[num] = (1 - current_auc) / (1 - base_auc)
        print(feature_name, ":", feature_importance[num])
    # Sort
    sort_list = np.flip(np.argsort(feature_importance))
    sorted_importance = feature_importance[sort_list]
    sorted_names = selected_feature_names[sort_list]
    print("Feature importance rank:", sorted_names)
    # Plot
    if num_feature > max_feature:
        num_show = max_feature
    else:
        num_show = num_feature
    ax.barh(
        np.flip(np.arange(num_show)),
        sorted_importance[:num_show],
        align="center",
        alpha=0.5,
        log=log,
    )
    ax.axhline(1, ls="--", color="r")
    ax.set_title("feature importance")
    ax.set_xticks(np.arange(num_show))
    ax.set_xticklabels(sorted_names[:num_show])


def plot_input_distributions(
    model_wrapper,
    apply_data=False,
    figsize=(8, 6),
    style_cfg_path=None,
    show_reshaped=False,
    dnn_cut=None,
    compare_cut_sb_separated=False,
    plot_density=True,
    save_fig=False,
    save_dir=None,
    save_format="png",
):
    """Plots input distributions comparision plots for sig/bkg/data"""
    print("Plotting input distributions.")
    config = {}
    if style_cfg_path is not None:
        with open(style_cfg_path) as plot_config_file:
            config = json.load(plot_config_file)

    model_meta = model_wrapper.model_meta
    sig_key = model_meta["sig_key"]
    bkg_key = model_meta["bkg_key"]
    if show_reshaped:
        bkg_array = model_wrapper.feedbox.get_array("xb", "reshape", array_key=bkg_key)
        sig_array = model_wrapper.feedbox.get_array("xs", "reshape", array_key=sig_key)
    else:
        bkg_array = model_wrapper.feedbox.get_array("xb", "raw", array_key=bkg_key)
        sig_array = model_wrapper.feedbox.get_array("xs", "raw", array_key=sig_key)
    bkg_fill_weights = np.reshape(bkg_array[:, -1], (-1, 1))
    sig_fill_weights = np.reshape(sig_array[:, -1], (-1, 1))
    if plot_density:
        bkg_fill_weights = bkg_fill_weights / np.sum(bkg_fill_weights)
        sig_fill_weights = sig_fill_weights / np.sum(sig_fill_weights)
    # get fill weights with dnn cut
    if dnn_cut is not None:
        assert dnn_cut >= 0 and dnn_cut <= 1, "dnn_cut out or range."
        model_meta = model_wrapper.model_meta
        # prepare signal
        sig_arr_temp = sig_array.copy()
        sig_arr_temp[:, 0:-2] = train_utils.norarray(
            sig_arr_temp[:, 0:-2],
            average=np.array(model_meta["norm_average"]),
            variance=np.array(model_meta["norm_variance"]),
        )
        sig_selected_arr = train_utils.get_valid_feature(sig_arr_temp)
        sig_predictions = model_wrapper.get_model().predict(sig_selected_arr)
        sig_cut_index = array_utils.get_cut_index(sig_predictions, [dnn_cut], ["<"])
        sig_fill_weights_dnn = sig_fill_weights.copy()
        sig_fill_weights_dnn[sig_cut_index] = 0
        # prepare background
        bkg_arr_temp = bkg_array.copy()
        bkg_arr_temp[:, 0:-2] = train_utils.norarray(
            bkg_arr_temp[:, 0:-2],
            average=np.array(model_meta["norm_average"]),
            variance=np.array(model_meta["norm_variance"]),
        )
        bkg_selected_arr = train_utils.get_valid_feature(bkg_arr_temp)
        bkg_predictions = model_wrapper.get_model().predict(bkg_selected_arr)
        bkg_cut_index = array_utils.get_cut_index(bkg_predictions, [dnn_cut], ["<"])
        bkg_fill_weights_dnn = bkg_fill_weights.copy()
        bkg_fill_weights_dnn[bkg_cut_index] = 0
        # normalize weights for density plots
        if plot_density:
            bkg_fill_weights_dnn = bkg_fill_weights_dnn / np.sum(bkg_fill_weights_dnn)
            sig_fill_weights_dnn = sig_fill_weights_dnn / np.sum(sig_fill_weights_dnn)
    # prepare thresholds
    for feature_id, feature in enumerate(model_wrapper.selected_features):
        bkg_fill_array = np.reshape(bkg_array[:, feature_id], (-1, 1))
        sig_fill_array = np.reshape(sig_array[:, feature_id], (-1, 1))
        # prepare background histogram
        hist_bkg = th1_tools.TH1FTool(
            feature + "_bkg", "bkg", nbin=100, xlow=-20, xup=20
        )
        hist_bkg.reinitial_hist_with_fill_array(bkg_fill_array)
        hist_bkg.fill_hist(bkg_fill_array, bkg_fill_weights)
        hist_bkg.set_config(config)
        hist_bkg.update_config("hist", "SetLineColor", 4)
        hist_bkg.update_config("hist", "SetFillStyle", 3354)
        hist_bkg.update_config("hist", "SetFillColor", ROOT.kBlue)
        hist_bkg.update_config("x_axis", "SetTitle", feature)
        hist_bkg.apply_config()
        # prepare signal histogram
        hist_sig = th1_tools.TH1FTool(
            feature + "_sig", "sig", nbin=100, xlow=-20, xup=20
        )
        hist_sig.reinitial_hist_with_fill_array(sig_fill_array)
        hist_sig.fill_hist(sig_fill_array, sig_fill_weights)
        hist_sig.set_config(config)
        hist_sig.update_config("hist", "SetLineColor", 2)
        hist_sig.update_config("hist", "SetFillStyle", 3354)
        hist_sig.update_config("hist", "SetFillColor", ROOT.kRed)
        hist_sig.update_config("x_axis", "SetTitle", feature)
        hist_sig.apply_config()
        # prepare bkg/sig histograms with dnn cut
        if dnn_cut is not None:
            hist_bkg_dnn = th1_tools.TH1FTool(
                feature + "_bkg_cut_dnn", "bkg_cut_dnn", nbin=100, xlow=-20, xup=20
            )
            hist_bkg_dnn.reinitial_hist_with_fill_array(bkg_fill_array)
            hist_bkg_dnn.fill_hist(bkg_fill_array, bkg_fill_weights_dnn)
            hist_bkg_dnn.set_config(config)
            hist_bkg_dnn.update_config("hist", "SetLineColor", 4)
            hist_bkg_dnn.update_config("hist", "SetFillStyle", 3001)
            hist_bkg_dnn.update_config("hist", "SetFillColor", ROOT.kBlue)
            hist_bkg_dnn.update_config("x_axis", "SetTitle", feature)
            hist_bkg_dnn.apply_config()
            hist_sig_dnn = th1_tools.TH1FTool(
                feature + "_sig_cut_dnn", "sig_cut_dnn", nbin=100, xlow=-20, xup=20
            )
            hist_sig_dnn.reinitial_hist_with_fill_array(sig_fill_array)
            hist_sig_dnn.fill_hist(sig_fill_array, sig_fill_weights_dnn)
            hist_sig_dnn.set_config(config)
            hist_sig_dnn.update_config("hist", "SetLineColor", 2)
            hist_sig_dnn.update_config("hist", "SetFillStyle", 3001)
            hist_sig_dnn.update_config("hist", "SetFillColor", ROOT.kRed)
            hist_sig_dnn.update_config("x_axis", "SetTitle", feature)
            hist_sig_dnn.apply_config()
        # combined histograms
        if not compare_cut_sb_separated:
            if dnn_cut is not None:
                hist_col = th1_tools.HistCollection(
                    [hist_bkg_dnn, hist_sig_dnn],
                    name=feature,
                    title="input var: " + feature,
                )
            else:
                hist_col = th1_tools.HistCollection(
                    [hist_bkg, hist_sig], name=feature, title="input var: " + feature
                )
            hist_col.draw(
                draw_options="hist",
                legend_title="legend",
                draw_norm=False,
                remove_empty_ends=True,
            )
            hist_col.save(
                save_dir=save_dir, save_file_name=feature, save_format=save_format
            )
        else:
            hist_col_bkg = th1_tools.HistCollection(
                [hist_bkg, hist_bkg_dnn],
                name=feature + "_bkg",
                title="input var: " + feature,
            )
            hist_col_bkg.draw(
                draw_options="hist",
                legend_title="legend",
                draw_norm=False,
                remove_empty_ends=True,
            )
            hist_col_bkg.save(
                save_dir=save_dir,
                save_file_name=feature + "_bkg",
                save_format=save_format,
            )
            hist_col_sig = th1_tools.HistCollection(
                [hist_sig, hist_sig_dnn],
                name=feature + "_sig",
                title="input var: " + feature,
            )
            hist_col_sig.draw(
                draw_options="hist",
                legend_title="legend",
                draw_norm=False,
                remove_empty_ends=True,
            )
            hist_col_sig.save(
                save_dir=save_dir,
                save_file_name=feature + "_sig",
                save_format=save_format,
            )


def plot_overtrain_check(ax, model_wrapper, bins=50, range=(-0.25, 1.25), log=True):
    """Plots train/test scores distribution to check overtrain"""
    print("Plotting train/test scores.")
    model = model_wrapper.get_model()
    feedbox = model_wrapper.feedbox
    model_meta = model_wrapper.model_meta
    sig_key = model_meta["sig_key"]
    bkg_key = model_meta["bkg_key"]
    # plot test scores
    (_, _, _, _, xs_train, xs_test, xb_train, xb_test,) = feedbox.get_train_test_arrays(
        sig_key=sig_key, bkg_key=bkg_key, use_selected=False
    )
    (
        _,
        _,
        _,
        _,
        xs_train_selected,
        xs_test_selected,
        xb_train_selected,
        xb_test_selected,
    ) = feedbox.get_train_test_arrays(
        sig_key=sig_key, bkg_key=bkg_key, use_selected=True
    )
    plot_scores(
        ax,
        model,
        xb_test_selected,
        xb_test[:, -1],
        xs_test_selected,
        xs_test[:, -1],
        apply_data=False,
        title="over training check",
        bkg_label="b-test",
        sig_label="s-test",
        bins=bins,
        range=range,
        density=True,
        log=log,
    )
    # plot train scores
    make_bar_plot(
        ax,
        model.predict(xb_train_selected),
        "b-train",
        weights=np.reshape(xb_train[:, -1], (-1, 1)),
        bins=bins,
        range=range,
        density=True,
        use_error=True,
        color="darkblue",
        fmt=".",
    )
    make_bar_plot(
        ax,
        model.predict(xs_train_selected),
        "s-train",
        weights=np.reshape(xs_train[:, -1], (-1, 1)),
        bins=bins,
        range=range,
        density=True,
        use_error=True,
        color="maroon",
        fmt=".",
    )


def plot_overtrain_check_original_mass(
    ax, model_wrapper, bins=50, range=(-0.25, 1.25), log=True
):
    """Plots train/test scores distribution to check overtrain"""
    print("Plotting train/test scores (original mass).")
    model = model_wrapper.get_model()
    feedbox = model_wrapper.feedbox
    model_meta = model_wrapper.model_meta
    sig_key = model_meta["sig_key"]
    bkg_key = model_meta["bkg_key"]
    (
        _,
        _,
        _,
        _,
        xs_train_original_mass,
        xs_test_original_mass,
        xb_train_original_mass,
        xb_test_original_mass,
    ) = feedbox.get_train_test_arrays(
        sig_key=sig_key, bkg_key=bkg_key, reset_mass=False, use_selected=False
    )
    (
        _,
        _,
        _,
        _,
        xs_train_selected_original_mass,
        xs_test_selected_original_mass,
        xb_train_selected_original_mass,
        xb_test_selected_original_mass,
    ) = feedbox.get_train_test_arrays(
        sig_key=sig_key, bkg_key=bkg_key, reset_mass=False, use_selected=True
    )

    # plot test scores
    plot_scores(
        ax,
        model,
        xb_test_selected_original_mass,
        xb_test_original_mass[:, -1],
        xs_test_selected_original_mass,
        xs_test_original_mass[:, -1],
        apply_data=False,
        title="over training check",
        bkg_label="b-test",
        sig_label="s-test",
        bins=bins,
        range=range,
        density=True,
        log=log,
    )
    # plot train scores
    make_bar_plot(
        ax,
        model.predict(xb_train_selected_original_mass),
        "b-train",
        weights=np.reshape(xb_train_original_mass[:, -1], (-1, 1)),
        bins=bins,
        range=range,
        density=True,
        use_error=True,
        color="darkblue",
        fmt=".",
    )
    make_bar_plot(
        ax,
        model.predict(xs_train_selected_original_mass),
        "s-train",
        weights=np.reshape(xs_train_original_mass[:, -1], (-1, 1)),
        bins=bins,
        range=range,
        density=True,
        use_error=True,
        color="maroon",
        fmt=".",
    )


def plot_loss(ax: plt.axes, loss_list: list, val_loss_list: list) -> None:
    """Plots loss vs training epoch."""
    print("Plotting loss curve.")
    # Plot
    ax.plot(loss_list)
    ax.plot(val_loss_list)
    # Config
    ax.set_title("model loss")
    ax.set_xlabel("epoch")
    ax.set_ylabel("loss")
    ax.legend(["train", "val"], loc="lower left")
    ax.grid()


def plot_roc(ax, xs, xb, model, yscal="logit", ylim=(0.1, 1 - 1e-4)):
    """Plots roc curve on given axes."""
    # Get data
    x_plot, y_plot, y_pred = process_array(xs, xb, model, rm_last_two=True)
    fpr_dm, tpr_dm, _ = roc_curve(y_plot, y_pred, sample_weight=x_plot[:, -1])
    # Make plots
    ax.plot(fpr_dm, tpr_dm)
    ax.set_title("roc curve")
    ax.set_xlabel("fpr")
    ax.set_ylabel("tpr")
    ax.set_ylim(ylim[0], ylim[-1])
    ax.set_yscale(yscal)
    ax.yaxis.set_minor_formatter(NullFormatter())
    # Calculate auc and return parameters
    auc_value = roc_auc_score(y_plot, y_pred)
    return auc_value, fpr_dm, tpr_dm


def plot_scores(
    ax,
    model,
    selected_bkg,
    bkg_weight,
    selected_sig,
    sig_weight,
    selected_data=None,
    data_weight=None,
    apply_data=False,
    title="scores",
    bkg_label="bkg",
    sig_label="sig",
    bins=50,
    range=(-0.25, 1.25),
    density=True,
    log=False,
):
    """Plots score distribution for siganl and background."""
    ax.hist(
        model.predict(selected_bkg),
        weights=bkg_weight,
        bins=bins,
        range=range,
        histtype="step",
        label=bkg_label,
        density=density,
        log=log,
        facecolor="blue",
        edgecolor="darkblue",
        alpha=0.5,
        fill=True,
    )
    ax.hist(
        model.predict(selected_sig),
        weights=sig_weight,
        bins=bins,
        range=range,
        histtype="step",
        label=sig_label,
        density=density,
        log=log,
        facecolor="red",
        edgecolor="maroon",
        hatch="///",
        alpha=1,
        fill=False,
    )
    if apply_data:
        make_bar_plot(
            ax,
            model.predict(selected_data),
            "data",
            weights=np.reshape(data_weight, (-1, 1)),
            bins=bins,
            range=range,
            density=density,
            use_error=False,
        )
    ax.set_title(title)
    ax.legend(loc="lower left")
    ax.set_xlabel("Output score")
    ax.set_ylabel("arb. unit")
    ax.grid()


def plot_scores_separate(
    ax,
    model_wrapper,
    bkg_dict,
    bkg_plot_key_list=None,
    sig_arr=None,
    sig_weights=None,
    apply_data=False,
    data_arr=None,
    data_weight=None,
    plot_title="all input scores",
    bins=50,
    range=(-0.25, 1.25),
    density=True,
    log=False,
):
    """Plots training score distribution for different background with matplotlib.

    Note:
        bkg_plot_key_list can be used to adjust order of background sample 
        stacking. For example, if bkg_plot_key_list = ['top', 'zll', 'diboson']
        'top' will be put at bottom & 'zll' in the middle & 'diboson' on the top

    """
    print("Plotting scores with bkg separated.")
    predict_arr_list = []
    predict_arr_weight_list = []
    model = model_wrapper.get_model()
    feedbox = model_wrapper.feedbox
    model_meta = model_wrapper.model_meta
    # plot background
    if (type(bkg_plot_key_list) is not list) or len(bkg_plot_key_list) == 0:
        # prepare plot key list sort with total weight by default
        original_keys = list(bkg_dict.keys())
        total_weight_list = []
        for key in original_keys:
            total_weight = np.sum((bkg_dict[key])[:, -1])
            total_weight_list.append(total_weight)
        sort_indexes = np.argsort(np.array(total_weight_list))
        bkg_plot_key_list = [original_keys[index] for index in sort_indexes]
    for arr_key in bkg_plot_key_list:
        bkg_arr_temp = bkg_dict[arr_key].copy()
        bkg_arr_temp[:, 0:-2] = train_utils.norarray(
            bkg_arr_temp[:, 0:-2],
            average=np.array(model_meta["norm_average"]),
            variance=np.array(model_meta["norm_variance"]),
        )
        selected_arr = train_utils.get_valid_feature(bkg_arr_temp)
        predict_arr_list.append(np.array(model.predict(selected_arr)))
        predict_arr_weight_list.append(bkg_arr_temp[:, -1])
    try:
        ax.hist(
            np.transpose(predict_arr_list),
            bins=bins,
            range=range,
            weights=np.transpose(predict_arr_weight_list),
            histtype="bar",
            label=bkg_plot_key_list,
            density=density,
            stacked=True,
        )
    except:
        ax.hist(
            predict_arr_list[0],
            bins=bins,
            range=range,
            weights=predict_arr_weight_list[0],
            histtype="bar",
            label=bkg_plot_key_list,
            density=density,
            stacked=True,
        )
    # plot signal
    if sig_arr is None:
        sig_key = model_meta["sig_key"]
        xs_reshape = feedbox.get_array("xs", "reshape", array_key=sig_key)
        selected_arr = train_utils.get_valid_feature(xs_reshape)
        predict_arr = model.predict(selected_arr)
        predict_weight_arr = xs_reshape[:, -1]
    else:
        sig_arr_temp = sig_arr.copy()
        sig_arr_temp[:, 0:-2] = train_utils.norarray(
            sig_arr[:, 0:-2],
            average=np.array(model_meta["norm_average"]),
            variance=np.array(model_meta["norm_variance"]),
        )
        selected_arr = train_utils.get_valid_feature(sig_arr_temp)
        predict_arr = np.array(model.predict(selected_arr))
        predict_weight_arr = sig_arr_temp[:, -1]
    ax.hist(
        predict_arr,
        bins=bins,
        range=range,
        weights=predict_weight_arr,
        histtype="step",
        label="sig",
        density=density,
    )
    # plot data
    if apply_data:
        data_key = model_meta["data_key"]
        if data_arr is None:
            xd = feedbox.get_array("xd", "raw", array_key=data_key)
            xd_selected = feedbox.get_array(
                "xd", "selected", array_key=data_key, reset_mass=False
            )
            data_arr = xd_selected
            data_weight = xd[:, -1]
        make_bar_plot(
            ax,
            model.predict(data_arr),
            "data",
            weights=np.reshape(data_weight, (-1, 1)),
            bins=bins,
            range=range,
            density=density,
            use_error=False,
        )
    ax.set_title(plot_title)
    ax.legend(loc="upper right")
    ax.set_xlabel("Output score")
    ax.set_ylabel("arb. unit")
    ax.grid()
    if log is True:
        ax.set_yscale("log")
        ax.set_title(plot_title + "(log)")
    else:
        ax.set_title(plot_title + "(lin)")


def plot_scores_separate_root(
    model_wrapper,
    bkg_plot_key_list,
    sig_arr=None,
    apply_data=False,
    apply_data_range=None,
    data_arr=None,
    plot_title="all input scores",
    bins=50,
    range=(-0.25, 1.25),
    scale_sig=False,
    density=True,
    log_scale=False,
    save_plot=False,
    save_dir=None,
    save_file_name=None,
):
    """Plots training score distribution for different background with ROOT

    Note:
        bkg_plot_key_list can be used to adjust order of background sample 
        stacking. For example, if bkg_plot_key_list = ['top', 'zll', 'diboson']
        'top' will be put at bottom & 'zll' in the middle & 'diboson' on the top

    """
    print("Plotting scores with bkg separated with ROOT.")
    model = model_wrapper.get_model()
    feedbox = model_wrapper.feedbox
    model_meta = model_wrapper.model_meta
    bkg_dict = feedbox.xb_dict
    plot_canvas = ROOT.TCanvas(plot_title, plot_title, 800, 800)
    plot_pad_score = ROOT.TPad("pad1", "pad1", 0, 0.3, 1, 1.0)
    plot_pad_score.SetBottomMargin(0)
    plot_pad_score.SetGridx()
    plot_pad_score.Draw()
    plot_pad_score.cd()
    hist_list = []
    # plot background
    if (type(bkg_plot_key_list) is not list) or len(bkg_plot_key_list) == 0:
        # prepare plot key list sort with total weight by default
        original_keys = list(bkg_dict.keys())
        total_weight_list = []
        for key in original_keys:
            if len(bkg_dict[key]) == 0:
                total_weight = 0
            else:
                total_weight = np.sum((bkg_dict[key])[:, -1])
            total_weight_list.append(total_weight)
        sort_indexes = np.argsort(np.array(total_weight_list))
        bkg_plot_key_list = [original_keys[index] for index in sort_indexes]
    for arr_key in bkg_plot_key_list:
        bkg_arr_temp = bkg_dict[arr_key].copy()
        bkg_arr_temp = array_utils.modify_array(bkg_arr_temp, select_channel=True)
        if len(bkg_arr_temp) != 0:
            bkg_arr_temp[:, 0:-2] = train_utils.norarray(
                bkg_arr_temp[:, 0:-2],
                average=np.array(model_meta["norm_average"]),
                variance=np.array(model_meta["norm_variance"]),
            )
            selected_arr = train_utils.get_valid_feature(bkg_arr_temp)
            predict_arr = np.array(model.predict(selected_arr))
            predict_weight_arr = bkg_arr_temp[:, -1]
        else:
            predict_arr = np.array([])
            predict_weight_arr = np.array([])
        th1_temp = th1_tools.TH1FTool(
            arr_key, arr_key, nbin=bins, xlow=range[0], xup=range[1]
        )
        th1_temp.fill_hist(predict_arr, predict_weight_arr)
        hist_list.append(th1_temp)
    hist_stacked_bkgs = th1_tools.THStackTool(
        "bkg stack plot", plot_title, hist_list, canvas=plot_pad_score
    )
    hist_stacked_bkgs.set_palette("kPastel")
    hist_stacked_bkgs.draw("pfc hist", log_scale=log_scale)
    hist_stacked_bkgs.get_hstack().GetYaxis().SetTitle("events/bin")
    hist_bkg_total = hist_stacked_bkgs.get_added_hist()
    total_weight_bkg = hist_bkg_total.get_hist().GetSumOfWeights()
    # plot signal
    if sig_arr is None:
        sig_key = model_meta["sig_key"]
        predict_weight_arr = feedbox.get_array("xs", "reshape", array_key=sig_key)[
            :, -1
        ]
        sig_arr_temp = feedbox.get_array("xs", "raw", array_key=sig_key)
    else:
        predict_weight_arr = sig_arr[:, -1]
        sig_arr_temp = sig_arr.copy()
    sig_arr_temp[:, 0:-2] = train_utils.norarray(
        sig_arr_temp[:, 0:-2],
        average=np.array(model_meta["norm_average"]),
        variance=np.array(model_meta["norm_variance"]),
    )
    selected_arr = train_utils.get_valid_feature(sig_arr_temp)
    predict_arr = model.predict(selected_arr)
    if scale_sig:
        sig_title = "sig-scaled"
    else:
        sig_title = "sig"
    hist_sig = th1_tools.TH1FTool(
        "sig added",
        sig_title,
        nbin=bins,
        xlow=range[0],
        xup=range[1],
        canvas=plot_pad_score,
    )
    hist_sig.fill_hist(predict_arr, predict_weight_arr)
    total_weight_sig = hist_sig.get_hist().GetSumOfWeights()
    if scale_sig:
        total_weight = hist_stacked_bkgs.get_total_weights()
        scale_factor = total_weight / hist_sig.get_hist().GetSumOfWeights()
        hist_sig.get_hist().Scale(scale_factor)
    hist_sig.update_config("hist", "SetLineColor", ROOT.kRed)
    # set proper y range
    maximum_y = max(
        plot_utils.get_highest_bin_value(hist_list),
        plot_utils.get_highest_bin_value(hist_sig),
    )
    hist_stacked_bkgs.get_hstack().SetMaximum(1.2 * maximum_y)
    hist_stacked_bkgs.get_hstack().SetMinimum(0.1)
    hist_stacked_bkgs.get_hstack().GetYaxis().SetLabelFont(43)
    hist_stacked_bkgs.get_hstack().GetYaxis().SetLabelSize(15)
    hist_sig.draw("same hist")
    # plot data if required
    total_weight_data = 0
    if apply_data:
        if data_arr is None:
            data_key = model_meta["data_key"]
            predict_weight_arr = feedbox.get_array("xd", "reshape", array_key=data_key)[
                :, -1
            ]
            data_arr_temp = feedbox.get_array("xd", "raw", array_key=data_key)
        else:
            predict_weight_arr = data_arr[:, -1]
            data_arr_temp = data_arr.copy()
        data_arr_temp = array_utils.modify_array(data_arr_temp, select_channel=True)
        data_arr_temp[:, 0:-2] = train_utils.norarray(
            data_arr_temp[:, 0:-2],
            average=np.array(model_meta["norm_average"]),
            variance=np.array(model_meta["norm_variance"]),
        )
        selected_arr = train_utils.get_valid_feature(data_arr_temp)
        predict_arr = model.predict(selected_arr)

        hist_data = th1_tools.TH1FTool(
            "data added",
            "data",
            nbin=bins,
            xlow=range[0],
            xup=range[1],
            canvas=plot_pad_score,
        )
        hist_data.fill_hist(predict_arr, predict_weight_arr)
        hist_data.update_config("hist", "SetMarkerStyle", ROOT.kFullCircle)
        hist_data.update_config("hist", "SetMarkerColor", ROOT.kBlack)
        hist_data.update_config("hist", "SetMarkerSize", 0.8)
        if apply_data_range is not None:
            hist_data.get_hist().GetXaxis().SetRangeUser(
                apply_data_range[0], apply_data_range[1]
            )
        hist_data.draw("same e1", log_scale=log_scale)
        total_weight_data = hist_data.get_hist().GetSumOfWeights()
    else:
        hist_data = hist_sig
        total_weight_data = 0
    hist_data.build_legend(0.4, 0.7, 0.6, 0.9)

    # ratio plot
    if apply_data:
        plot_canvas.cd()
        plot_pad_ratio = ROOT.TPad("pad2", "pad2", 0, 0.05, 1, 0.3)
        plot_pad_ratio.SetTopMargin(0)
        plot_pad_ratio.SetGridx()
        plot_pad_ratio.Draw()
        ratio_plot = th1_tools.RatioPlot(
            hist_data,
            hist_bkg_total,
            x_title="DNN Score",
            y_title="data/bkg",
            canvas=plot_pad_ratio,
        )
        ratio_plot.draw()

    # show & save total weight info
    model_wrapper.total_weight_sig = total_weight_sig
    print("sig total weight:", total_weight_sig)
    model_wrapper.total_weight_bkg = total_weight_bkg
    print("bkg total weight:", total_weight_bkg)
    model_wrapper.total_weight_data = total_weight_data
    print("data total weight:", total_weight_data)
    # save plot
    if save_plot:
        plot_canvas.SaveAs(save_dir + "/" + save_file_name + ".png")


def plot_significance_scan(
    ax, model_wrapper, save_dir=".", significance_algo="asimov", suffix=""
) -> None:
    """Shows significance change with threshold.

    Note:
        significance is calculated by s/sqrt(b)
    """
    print("Plotting significance scan.")

    (
        plot_thresholds,
        significances,
        sig_above_threshold,
        bkg_above_threshold,
    ) = get_significances(model_wrapper, significance_algo=significance_algo)

    significances_no_nan = np.nan_to_num(significances)
    max_significance = np.amax(significances_no_nan)
    index = np.argmax(significances_no_nan)
    max_significance_threshold = plot_thresholds[index]
    max_significance_sig_total = sig_above_threshold[index]
    max_significance_bkg_total = bkg_above_threshold[index]
    total_sig_weight = sig_above_threshold[0]
    total_bkg_weight = bkg_above_threshold[0]
    # make plots
    # plot original significance
    original_significance = train_utils.calculate_significance(
        total_sig_weight,
        total_bkg_weight,
        sig_total=total_sig_weight,
        bkg_total=total_bkg_weight,
        algo=significance_algo,
    )
    ax.axhline(y=original_significance, color="grey", linestyle="--")
    # significance scan curve
    ax.plot(plot_thresholds, significances_no_nan, color="r", label=significance_algo)
    # signal/background events scan curve
    ax2 = ax.twinx()
    max_sig_events = sig_above_threshold[0]
    max_bkg_events = bkg_above_threshold[0]
    sig_eff_above_threshold = np.array(sig_above_threshold) / max_sig_events
    bkg_eff_above_threshold = np.array(bkg_above_threshold) / max_bkg_events
    ax2.plot(plot_thresholds, sig_eff_above_threshold, color="orange", label="sig")
    ax2.plot(plot_thresholds, bkg_eff_above_threshold, color="blue", label="bkg")
    ax2.set_ylabel("sig(bkg) ratio after cut")
    # reference threshold
    ax.axvline(x=max_significance_threshold, color="green", linestyle="-.")
    # more infomation
    content = (
        "best threshold:"
        + str(common_utils.get_significant_digits(max_significance_threshold, 6))
        + "\nmax significance:"
        + str(common_utils.get_significant_digits(max_significance, 6))
        + "\nbase significance:"
        + str(common_utils.get_significant_digits(original_significance, 6))
        + "\nsig events above threshold:"
        + str(common_utils.get_significant_digits(max_significance_sig_total, 6))
        + "\nbkg events above threshold:"
        + str(common_utils.get_significant_digits(max_significance_bkg_total, 6))
    )
    ax.text(
        0.05,
        0.9,
        content,
        verticalalignment="top",
        horizontalalignment="left",
        transform=ax.transAxes,
        color="green",
        fontsize=12,
    )
    # set up plot
    ax.set_title("significance scan")
    ax.set_xscale("logit")
    ax.set_xlabel("DNN score threshold")
    ax.set_ylabel("significance")
    ax.set_ylim(bottom=0)
    ax.locator_params(nbins=10, axis="x")
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.legend(loc="center left")
    ax2.legend(loc="center right")
    # ax2.set_yscale("log")
    # collect meta data
    model_wrapper.original_significance = original_significance
    model_wrapper.max_significance = max_significance
    model_wrapper.max_significance_threshold = max_significance_threshold
    # make extra cut table 0.1, 0.2 ... 0.8, 0.9
    # make table for different DNN cut scores
    save_path = save_dir + "/scan_DNN_cut" + suffix + ".csv"
    with open(save_path, "w", newline="") as file:
        writer = csv.writer(file)
        row_list = [
            [
                "DNN cut",
                "sig events",
                "sig efficiency",
                "bkg events",
                "bkg efficiency",
                "significance",
            ]
        ]
        for index in range(1, 100):
            dnn_cut = (100 - index) / 100.0
            threshold_id = (np.abs(np.array(plot_thresholds) - dnn_cut)).argmin()
            sig_events = sig_above_threshold[threshold_id]
            sig_eff = sig_eff_above_threshold[threshold_id]
            bkg_events = bkg_above_threshold[threshold_id]
            bkg_eff = bkg_eff_above_threshold[threshold_id]
            significance = significances[threshold_id]
            new_row = [dnn_cut, sig_events, sig_eff, bkg_events, bkg_eff, significance]
            row_list.append(new_row)
        row_list.append([""])
        row_list.append(
            [
                "total sig",
                max_sig_events,
                "total bkg",
                max_bkg_events,
                "base significance",
                original_significance,
            ]
        )
        writer.writerows(row_list)
    # make table for different sig efficiency
    save_path = save_dir + "/scan_sig_eff" + suffix + ".csv"
    with open(save_path, "w", newline="") as file:
        writer = csv.writer(file)
        row_list = [
            [
                "DNN cut",
                "sig events",
                "sig efficiency",
                "bkg events",
                "bkg efficiency",
                "significance",
            ]
        ]
        for index in range(1, 100):
            sig_eff_cut = (100 - index) / 100.0
            threshold_id = (
                np.abs(np.array(sig_eff_above_threshold) - sig_eff_cut)
            ).argmin()
            dnn_cut = plot_thresholds[threshold_id]
            sig_events = sig_above_threshold[threshold_id]
            sig_eff = sig_eff_cut
            bkg_events = bkg_above_threshold[threshold_id]
            bkg_eff = bkg_eff_above_threshold[threshold_id]
            significance = significances[threshold_id]
            new_row = [dnn_cut, sig_events, sig_eff, bkg_events, bkg_eff, significance]
            row_list.append(new_row)
        row_list.append([""])
        row_list.append(
            [
                "total sig",
                max_sig_events,
                "total bkg",
                max_bkg_events,
                "base significance",
                original_significance,
            ]
        )
        writer.writerows(row_list)
    # make table for different bkg efficiency
    save_path = save_dir + "/scan_bkg_eff" + suffix + ".csv"
    with open(save_path, "w", newline="") as file:
        writer = csv.writer(file)
        row_list = [
            [
                "DNN cut",
                "sig events",
                "sig efficiency",
                "bkg events",
                "bkg efficiency",
                "significance",
            ]
        ]
        for index in range(1, 100):
            bkg_eff_cut = (100 - index) / 100.0
            threshold_id = (
                np.abs(np.array(bkg_eff_above_threshold) - bkg_eff_cut)
            ).argmin()
            dnn_cut = plot_thresholds[threshold_id]
            sig_events = sig_above_threshold[threshold_id]
            sig_eff = sig_eff_above_threshold[threshold_id]
            bkg_events = bkg_above_threshold[threshold_id]
            bkg_eff = bkg_eff_cut
            significance = significances[threshold_id]
            new_row = [dnn_cut, sig_events, sig_eff, bkg_events, bkg_eff, significance]
            row_list.append(new_row)
        row_list.append([""])
        row_list.append(
            [
                "total sig",
                max_sig_events,
                "total bkg",
                max_bkg_events,
                "base significance",
                original_significance,
            ]
        )
        writer.writerows(row_list)


def plot_train_test_roc(ax, model_wrapper, yscal="logit", ylim=(0.1, 1 - 1e-4)):
    """Plots roc curve."""
    print("Plotting train/test roc curve.")
    model = model_wrapper.get_model()
    feedbox = model_wrapper.feedbox
    model_meta = model_wrapper.model_meta
    sig_key = model_meta["sig_key"]
    bkg_key = model_meta["bkg_key"]
    (_, _, _, _, xs_train, xs_test, xb_train, xb_test,) = feedbox.get_train_test_arrays(
        sig_key=sig_key, bkg_key=bkg_key, use_selected=False
    )
    (
        _,
        _,
        _,
        _,
        xs_train_original_mass,
        xs_test_original_mass,
        xb_train_original_mass,
        xb_test_original_mass,
    ) = feedbox.get_train_test_arrays(
        sig_key=sig_key, bkg_key=bkg_key, use_selected=False, reset_mass=False
    )
    # First plot roc for train dataset
    auc_train, _, _ = plot_roc(ax, xs_train, xb_train, model)
    # Then plot roc for test dataset
    auc_test, _, _ = plot_roc(ax, xs_test, xb_test, model)
    # Then plot roc for train dataset without reseting mass
    auc_train_original, _, _ = plot_roc(
        ax,
        xs_train_original_mass,
        xb_train_original_mass,
        model,
        yscal=yscal,
        ylim=ylim,
    )
    # Lastly, plot roc for test dataset without reseting mass
    auc_test_original, _, _ = plot_roc(
        ax, xs_test_original_mass, xb_test_original_mass, model, yscal=yscal, ylim=ylim,
    )
    # Show auc value:
    plot_auc_text(
        ax,
        ["TV ", "TE ", "TVO", "TEO"],
        [auc_train, auc_test, auc_train_original, auc_test_original],
    )
    # Extra plot config
    ax.legend(
        [
            "TV (train+val)",
            "TE (test)",
            "TVO (train+val original)",
            "TEO (test original)",
        ],
        loc="lower right",
    )
    ax.grid()
    # Collect meta data
    auc_dict = {}
    auc_dict["auc_train"] = auc_train
    auc_dict["auc_test"] = auc_test
    auc_dict["auc_train_original"] = auc_train_original
    auc_dict["auc_test_original"] = auc_test_original
    return auc_dict


def process_array(xs, xb, model, shuffle_col=None, rm_last_two=False):
    """Process sig/bkg arrays in the same way for training arrays."""
    # Get data
    xs_proc = xs.copy()
    xb_proc = xb.copy()
    x_proc = np.concatenate((xs_proc, xb_proc))
    if shuffle_col is not None:
        # randomize x values but don't change overall distribution
        x_proc = array_utils.reset_col(x_proc, x_proc, shuffle_col)
    if rm_last_two:
        x_proc_selected = train_utils.get_valid_feature(x_proc)
    else:
        x_proc_selected = x_proc
    y_proc = np.concatenate((np.ones(xs_proc.shape[0]), np.zeros(xb_proc.shape[0])))
    y_pred = model.predict(x_proc_selected)
    return x_proc, y_proc, y_pred


def make_bar_plot(
    ax,
    datas,
    labels: list,
    weights,
    bins: int,
    range: tuple,
    title: str = None,
    x_lable: str = None,
    y_lable: str = None,
    x_unit: str = None,
    x_scale: float = None,
    density: bool = False,
    use_error: bool = False,
    color: str = "black",
    fmt: str = ".k",
) -> None:
    """Plot with verticle bar, can be used for data display.

        Note:
        According to ROOT:
        "The error per bin will be computed as sqrt(sum of squares of weight) for each bin."

    """
    plt.ioff()
    # Check input
    data_1dim = np.array([])
    weight_1dim = np.array([])
    if isinstance(datas, np.ndarray):
        datas = [datas]
        weights = [weights]
    for data, weight in zip(datas, weights):
        assert isinstance(data, np.ndarray), "datas element should be numpy array."
        assert isinstance(weight, np.ndarray), "weights element should be numpy array."
        assert (
            data.shape == weight.shape
        ), "Input weights should be None or have same type as arrays."
        if len(data_1dim) == 0:
            data_1dim = data
            weight_1dim = weight
        else:
            data_1dim = np.concatenate((data_1dim, data))
            weight_1dim = np.concatenate((weight_1dim, weight))

    # Scale x axis
    if x_scale is not None:
        data_1dim = data_1dim * x_scale
    # Make bar plot
    # get bin error and edges
    plot_ys, _ = np.histogram(
        data_1dim, bins=bins, range=range, weights=weight_1dim, density=density
    )
    sum_weight_squares, bin_edges = np.histogram(
        data_1dim, bins=bins, range=range, weights=np.power(weight_1dim, 2)
    )
    if density:
        error_scale = 1 / (np.sum(weight_1dim) * (range[1] - range[0]) / bins)
        errors = np.sqrt(sum_weight_squares) * error_scale
    else:
        errors = np.sqrt(sum_weight_squares)
    # Only plot ratio when bin is not 0.
    bin_centers = np.array([])
    bin_ys = np.array([])
    bin_yerrs = np.array([])
    for i, y1 in enumerate(plot_ys):
        if y1 != 0:
            ele_center = np.array([0.5 * (bin_edges[i] + bin_edges[i + 1])])
            bin_centers = np.concatenate((bin_centers, ele_center))
            ele_y = np.array([y1])
            bin_ys = np.concatenate((bin_ys, ele_y))
            ele_yerr = np.array([errors[i]])
            bin_yerrs = np.concatenate((bin_yerrs, ele_yerr))
    # plot bar
    bin_size = bin_edges[1] - bin_edges[0]
    if use_error:
        ax.errorbar(
            bin_centers,
            bin_ys,
            xerr=bin_size / 2.0,
            yerr=bin_yerrs,
            fmt=fmt,
            label=labels,
            color=color,
            markerfacecolor=color,
            markeredgecolor=color,
        )
    else:
        ax.errorbar(
            bin_centers,
            bin_ys,
            xerr=bin_size / 2.0,
            yerr=None,
            fmt=fmt,
            label=labels,
            color=color,
            markerfacecolor=color,
            markeredgecolor=color,
        )
    # Config
    if title is not None:
        ax.set_title(title)
    if x_lable is not None:
        if x_unit is not None:
            ax.set_xlabel(x_lable + "/" + x_unit)
        else:
            ax.set_xlabel(x_lable)
    else:
        if x_unit is not None:
            ax.set_xlabel(x_unit)
    if y_lable is not None:
        ax.set_ylabel(y_lable)
    if range is not None:
        ax.axis(xmin=range[0], xmax=range[1])
    ax.legend(loc="upper right")


def plot_2d_density(
    job_wrapper, save_plot=False, save_dir=None, save_file_name="2d_density",
):
    """Plots 2D hist to see event distribution of signal and backgrounds events.

    x-axis will be dnn scores, y-axis will be mass parameter, z-axis is total
    weight shown by color

    """
    model_wrapper = job_wrapper.model_wrapper
    feedbox = model_wrapper.feedbox
    model_meta = model_wrapper.model_meta
    # plot signal
    sig_key = model_meta["sig_key"]
    sig_arr_original = feedbox.get_array("xs", "raw", array_key=sig_key)
    sig_arr_temp = feedbox.get_array("xs", "raw", array_key=sig_key)
    sig_arr_temp[:, 0:-2] = train_utils.norarray(
        sig_arr_temp[:, 0:-2],
        average=np.array(model_meta["norm_average"]),
        variance=np.array(model_meta["norm_variance"]),
    )
    selected_arr = train_utils.get_valid_feature(sig_arr_temp)
    predict_arr = model_wrapper.get_model().predict(selected_arr)
    mass_index = job_wrapper.selected_features.index(job_wrapper.reset_feature_name)
    x = predict_arr
    y = sig_arr_original[:, mass_index]
    w = sig_arr_temp[:, -1]
    ## make plot
    plot_canvas = ROOT.TCanvas("2d_density_sig", "2d_density_sig", 1200, 900)
    hist_sig = th1_tools.TH2FTool(
        "2d_density_sig",
        "2d_density_sig",
        nbinx=50,
        xlow=0,
        xup=1.0,
        nbiny=50,
        ylow=min(y),
        yup=max(y),
    )
    hist_sig.fill_hist(fill_array_x=x, fill_array_y=y, weight_array=w)
    hist_sig.set_canvas(plot_canvas)
    hist_sig.set_palette("kBird")
    hist_sig.update_config("hist", "SetStats", 0)
    hist_sig.update_config("x_axis", "SetTitle", "dnn score")
    hist_sig.update_config("y_axis", "SetTitle", "mass")
    hist_sig.draw("colz")
    hist_sig.save(save_dir=save_dir, save_file_name=save_file_name + "_sig")
    # plot background
    bkg_key = model_meta["bkg_key"]
    bkg_arr_original = feedbox.get_array("xb", "raw", array_key=bkg_key)
    bkg_arr_temp = feedbox.get_array("xb", "raw", array_key=bkg_key)
    bkg_arr_temp[:, 0:-2] = train_utils.norarray(
        bkg_arr_temp[:, 0:-2],
        average=np.array(model_meta["norm_average"]),
        variance=np.array(model_meta["norm_variance"]),
    )
    selected_arr = train_utils.get_valid_feature(bkg_arr_temp)
    predict_arr = model_wrapper.get_model().predict(selected_arr)
    mass_index = job_wrapper.selected_features.index(job_wrapper.reset_feature_name)
    x = predict_arr
    y = bkg_arr_original[:, mass_index]
    w = bkg_arr_temp[:, -1]
    ## make plot
    plot_canvas = ROOT.TCanvas("2d_density_bkg", "2d_density_bkg", 1200, 900)
    hist_bkg = th1_tools.TH2FTool(
        "2d_density_bkg",
        "2d_density_bkg",
        nbinx=50,
        xlow=0,
        xup=1.0,
        nbiny=50,
        ylow=min(y),
        yup=max(y),
    )
    hist_bkg.fill_hist(fill_array_x=x, fill_array_y=y, weight_array=w)
    hist_bkg.set_canvas(plot_canvas)
    hist_bkg.set_palette("kBird")
    hist_bkg.update_config("hist", "SetStats", 0)
    hist_bkg.update_config("x_axis", "SetTitle", "dnn score")
    hist_bkg.update_config("y_axis", "SetTitle", "mass")
    hist_bkg.draw("colz")
    hist_bkg.save(save_dir=save_dir, save_file_name=save_file_name + "_bkg")


def plot_2d_significance_scan(
    job_wrapper,
    save_plot=False,
    save_dir=None,
    save_file_name="2d_significance",
    cut_ranges_dn=None,
    cut_ranges_up=None,
):
    """Makes 2d map of significance"""
    dnn_cut_list = np.arange(0.8, 1.0, 0.02)
    w_inputs = []
    print("Making 2d significance scan.")
    sig_dict = get_arrays.get_npy_individuals(
        job_wrapper.npy_path,
        job_wrapper.campaign,
        job_wrapper.channel,
        job_wrapper.sig_list,
        job_wrapper.selected_features,
        "sig",
        cut_features=job_wrapper.cut_features,
        cut_values=job_wrapper.cut_values,
        cut_types=job_wrapper.cut_types,
    )
    bkg_dict = get_arrays.get_npy_individuals(
        job_wrapper.npy_path,
        job_wrapper.campaign,
        job_wrapper.channel,
        job_wrapper.bkg_list,
        job_wrapper.selected_features,
        "bkg",
        cut_features=job_wrapper.cut_features,
        cut_values=job_wrapper.cut_values,
        cut_types=job_wrapper.cut_types,
    )
    for sig_id, scan_sig_key in enumerate(job_wrapper.sig_list):
        xs = array_utils.modify_array(sig_dict[scan_sig_key], select_channel=True)
        m_cut_name = job_wrapper.reset_feature_name
        if cut_ranges_dn is None or len(cut_ranges_dn) == 0:
            means, variances = train_utils.get_mean_var(
                xs[:, 0:-2], axis=0, weights=xs[:, -1]
            )
            m_index = job_wrapper.selected_features.index(m_cut_name)
            m_cut_dn = means[m_index] - math.sqrt(variances[m_index])
            m_cut_up = means[m_index] + math.sqrt(variances[m_index])
        else:
            m_cut_dn = cut_ranges_dn[sig_id]
            m_cut_up = cut_ranges_up[sig_id]
        feedbox = feed_box.Feedbox(
            sig_dict,
            bkg_dict,
            selected_features=job_wrapper.selected_features,
            apply_data=False,
            reshape_array=job_wrapper.norm_array,
            reset_mass=job_wrapper.reset_feature,
            reset_mass_name=job_wrapper.reset_feature_name,
            remove_negative_weight=job_wrapper.rm_negative_weight_events,
            cut_features=[m_cut_name, m_cut_name],
            cut_values=[m_cut_dn, m_cut_up],
            cut_types=[">", "<"],
            sig_weight=job_wrapper.sig_sumofweight,
            bkg_weight=job_wrapper.bkg_sumofweight,
            data_weight=job_wrapper.data_sumofweight,
            test_rate=job_wrapper.test_rate,
            rdm_seed=None,
            model_meta=job_wrapper.model_wrapper.model_meta,
            verbose=job_wrapper.verbose,
        )
        job_wrapper.model_wrapper.set_inputs(feedbox, apply_data=job_wrapper.apply_data)
        (plot_thresholds, significances, _, _,) = get_significances(
            job_wrapper.model_wrapper, significance_algo=job_wrapper.significance_algo,
        )
        plot_significances = []
        for dnn_cut in dnn_cut_list:
            threshold_id = (np.abs(np.array(plot_thresholds) - dnn_cut)).argmin()
            plot_significances.append(significances[threshold_id])
        w_inputs.append(plot_significances)
    x = []
    y = []
    w = []
    for index, w_input in enumerate(w_inputs):
        if len(x) == 0:
            x = dnn_cut_list.tolist()
            y = [job_wrapper.sig_list[index]] * len(w_input)
            w = w_input
        else:
            x += dnn_cut_list.tolist()
            y += [job_wrapper.sig_list[index]] * len(w_input)
            w += w_input
    # make plot
    plot_canvas = ROOT.TCanvas("2d_significance_c", "2d_significance_c", 1200, 900)
    hist_sig = th1_tools.TH2FTool(
        "2d_significance",
        "2d_significance",
        nbinx=10,
        xlow=0.8,
        xup=1.0,
        nbiny=len(job_wrapper.sig_list),
        ylow=0,
        yup=len(job_wrapper.sig_list),
    )
    hist_sig_text = th1_tools.TH2FTool(
        "2d_significance_text",
        "2d_significance_text",
        nbinx=10,
        xlow=0.8,
        xup=1.0,
        nbiny=len(job_wrapper.sig_list),
        ylow=0,
        yup=len(job_wrapper.sig_list),
    )
    hist_sig.fill_hist(fill_array_x=x, fill_array_y=y, weight_array=w)
    hist_sig.set_canvas(plot_canvas)
    hist_sig.set_palette("kBird")
    hist_sig.update_config("hist", "SetStats", 0)
    hist_sig.update_config("x_axis", "SetTitle", "dnn_cut")
    hist_sig.update_config("y_axis", "SetTitle", "mass point")
    hist_sig.draw("colz")
    hist_sig_text.fill_hist(
        fill_array_x=x, fill_array_y=y, weight_array=np.array(w).round(decimals=2)
    )
    hist_sig_text.set_canvas(plot_canvas)
    hist_sig_text.update_config("hist", "SetMarkerSize", 1.8)
    hist_sig_text.draw("text same")
    if save_plot:
        plot_canvas.SaveAs(save_dir + "/" + save_file_name + ".png")
