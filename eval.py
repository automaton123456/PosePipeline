import warnings

import cv2
import numpy as np


def _calc_distances(preds, targets, mask, normalize):
    """Calculate the normalized distances between preds and target.
    Note:
        batch_size: N
        num_keypoints: K
    Args:
        preds (np.ndarray[N, K, 2]): Predicted keypoint location.
        targets (np.ndarray[N, K, 2]): Groundtruth keypoint location.
        mask (np.ndarray[N, K]): Visibility of the target. False for invisible
            joints, and True for visible. Invisible joints will be ignored for
            accuracy calculation.
        normalize (np.ndarray[N, 2]): Typical value is heatmap_size
    Returns:
        np.ndarray[K, N]: The normalized distances.
          If target keypoints are missing, the distance is -1.
    """
    N, K, _ = preds.shape
    distances = np.full((N, K), -1, dtype=np.float32)
    distances[mask] = np.linalg.norm(
        ((preds - targets) / normalize[:, None, :])[mask], axis=-1)
    return distances.T


def _distance_acc(distances, thr=0.5):
    """Return the percentage below the distance threshold, while ignoring
    distances values with -1.
    Note:
        batch_size: N
    Args:
        distances (np.ndarray[N, ]): The normalized distances.
        thr (float): Threshold of the distances.
    Returns:
        float: Percentage of distances below the threshold.
          If all target keypoints are missing, return -1.
    """
    distance_valid = distances != -1
    num_distance_valid = distance_valid.sum()
    if num_distance_valid > 0:
        return (distances[distance_valid] < thr).sum() / num_distance_valid
    return -1


def _get_max_preds(heatmaps):
    """Get keypoint predictions from score maps.
    Note:
        batch_size: N
        num_keypoints: K
        heatmap height: H
        heatmap width: W
    Args:
        heatmaps (np.ndarray[N, K, H, W]): model predicted heatmaps.
    Returns:
        tuple: A tuple containing aggregated results.
        - preds (np.ndarray[N, K, 2]): Predicted keypoint location.
        - maxvals (np.ndarray[N, K, 1]): Scores (confidence) of the keypoints.
    """
    assert isinstance(heatmaps,
                      np.ndarray), ('heatmaps should be numpy.ndarray')
    assert heatmaps.ndim == 4, 'batch_images should be 4-ndim'

    N, K, _, W = heatmaps.shape
    heatmaps_reshaped = heatmaps.reshape((N, K, -1))
    idx = np.argmax(heatmaps_reshaped, 2).reshape((N, K, 1))
    maxvals = np.amax(heatmaps_reshaped, 2).reshape((N, K, 1))

    preds = np.tile(idx, (1, 1, 2)).astype(np.float32)
    preds[:, :, 0] = preds[:, :, 0] % W
    preds[:, :, 1] = preds[:, :, 1] // W

    preds = np.where(np.tile(maxvals, (1, 1, 2)) > 0.0, preds, -1)
    return preds, maxvals


def pose_pck_accuracy(output, target, mask, thr=0.05, normalize=None):
    """Calculate the pose accuracy of PCK for each individual keypoint and the
    averaged accuracy across all keypoints from heatmaps.
    Note:
        PCK metric measures accuracy of the localization of the body joints.
        The distances between predicted positions and the ground-truth ones
        are typically normalized by the bounding box size.
        The threshold (thr) of the normalized distance is commonly set
        as 0.05, 0.1 or 0.2 etc.
        batch_size: N
        num_keypoints: K
        heatmap height: H
        heatmap width: W
    Args:
        output (np.ndarray[N, K, H, W]): Model output heatmaps.
        target (np.ndarray[N, K, H, W]): Groundtruth heatmaps.
        mask (np.ndarray[N, K]): Visibility of the target. False for invisible
            joints, and True for visible. Invisible joints will be ignored for
            accuracy calculation.
        thr (float): Threshold of PCK calculation. Default 0.05.
        normalize (np.ndarray[N, 2]): Normalization factor for H&W.
    Returns:
        tuple: A tuple containing keypoint accuracy.
        - np.ndarray[K]: Accuracy of each keypoint.
        - float: Averaged accuracy across all keypoints.
        - int: Number of valid keypoints.
    """

    if len(output.shape) == 3:
        output = np.expand_dims(output, axis=0)

    if len(target.shape) == 3:
        target = np.expand_dims(target, axis=0)

    if len(mask.shape) == 3:
        mask = np.reshape(mask, (1,17))


    target = np.transpose(target, (0,3,1,2))
    output = np.transpose(output, (0,3,1,2))
    mask = np.array(mask)
    mask = mask.astype(np.bool)


    N, K, H, W = output.shape
    if K == 0:
        return None, 0, 0
    if normalize is None:
        normalize = np.tile(np.array([[H, W]]), (N, 1))

    pred, _ = _get_max_preds(output)
    gt, _ = _get_max_preds(target)
    return keypoint_pck_accuracy(pred, gt, mask, thr, normalize)


def keypoint_pck_accuracy(pred, gt, mask, thr, normalize):
    """Calculate the pose accuracy of PCK for each individual keypoint and the
    averaged accuracy across all keypoints for coordinates.
    Note:
        PCK metric measures accuracy of the localization of the body joints.
        The distances between predicted positions and the ground-truth ones
        are typically normalized by the bounding box size.
        The threshold (thr) of the normalized distance is commonly set
        as 0.05, 0.1 or 0.2 etc.
        batch_size: N
        num_keypoints: K
    Args:
        pred (np.ndarray[N, K, 2]): Predicted keypoint location.
        gt (np.ndarray[N, K, 2]): Groundtruth keypoint location.
        mask (np.ndarray[N, K]): Visibility of the target. False for invisible
            joints, and True for visible. Invisible joints will be ignored for
            accuracy calculation.
        thr (float): Threshold of PCK calculation.
        normalize (np.ndarray[N, 2]): Normalization factor for H&W.
    Returns:
        tuple: A tuple containing keypoint accuracy.
        - acc (np.ndarray[K]): Accuracy of each keypoint.
        - avg_acc (float): Averaged accuracy across all keypoints.
        - cnt (int): Number of valid keypoints.
    """
    distances = _calc_distances(pred, gt, mask, normalize)

    acc = np.array([_distance_acc(d, thr) for d in distances])
    valid_acc = acc[acc >= 0]
    cnt = len(valid_acc)
    avg_acc = valid_acc.mean() if cnt > 0 else 0
    return acc, avg_acc, cnt


def keypoint_auc(pred, gt, mask, normalize, num_step=20):
    """Calculate the pose accuracy of PCK for each individual keypoint and the
    averaged accuracy across all keypoints for coordinates.
    Note:
        batch_size: N
        num_keypoints: K
    Args:
        pred (np.ndarray[N, K, 2]): Predicted keypoint location.
        gt (np.ndarray[N, K, 2]): Groundtruth keypoint location.
        mask (np.ndarray[N, K]): Visibility of the target. False for invisible
            joints, and True for visible. Invisible joints will be ignored for
            accuracy calculation.
        normalize (float): Normalization factor.
    Returns:
        float: Area under curve.
    """
    nor = np.tile(np.array([[normalize, normalize]]), (pred.shape[0], 1))
    x = [1.0 * i / num_step for i in range(num_step)]
    y = []
    for thr in x:
        _, avg_acc, _ = keypoint_pck_accuracy(pred, gt, mask, thr, nor)
        y.append(avg_acc)

    auc = 0
    for i in range(num_step):
        auc += 1.0 / num_step * y[i]
    return auc


def keypoint_epe(pred, gt, mask):
    """Calculate the end-point error.
    Note:
        batch_size: N
        num_keypoints: K
    Args:
        pred (np.ndarray[N, K, 2]): Predicted keypoint location.
        gt (np.ndarray[N, K, 2]): Groundtruth keypoint location.
        mask (np.ndarray[N, K]): Visibility of the target. False for invisible
            joints, and True for visible. Invisible joints will be ignored for
            accuracy calculation.
    Returns:
        float: Average end-point error.
    """
    distances = _calc_distances(
        pred, gt, mask, np.tile(np.array([[1, 1]]), (pred.shape[0], 1)))
    distance_valid = distances[distances != -1]
    valid_num = len(distance_valid)
    return distance_valid.sum() / valid_num
