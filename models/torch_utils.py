import torch
import torch.nn.functional as F

from torch.utils.cpp_extension import load

get_canvas_cpp = load(name='canvas', sources=['models/get_canvas.cpp'])


def new_arange(x, *size):
    """
    Return a Tensor of `size` filled with a range function on the device of x.
    If size is empty, using the size of the variable x.
    """
    if len(size) == 0:
        size = x.size()
    return torch.arange(size[-1], device=x.device).expand(*size).contiguous()


def seq_cross_entropy(pred, gold, pad):
    """Calculate cross entropy loss"""

    gold_shape = gold.shape
    pred = pred.view(-1, pred.size(-1))
    gold = gold.view(-1)
    loss = F.cross_entropy(pred, gold, ignore_index=pad, reduction='none')

    return loss.view(gold_shape)


def batch_randint(start, batch_end):
    # Sample k from start to end (both inclusive) for start end in batch_end
    return start + (torch.rand_like(batch_end.float()) * (batch_end - start + 1).float()).long()


def to_tensor(x, pad_id, device):
    max_len = max([len(xi) for xi in x])
    x_ = [xi + [pad_id] * (max_len - len(xi)) for xi in x]
    return torch.tensor(x_).to(device)


def sample_permutation(seq, vocab):
    score = torch.rand_like(seq.float())
    score.masked_fill_(seq == vocab.pad, 1)         # always put pads last
    score.masked_fill_(seq == vocab.first, -1)      # always keep <first>
    score.masked_fill_(seq == vocab.last, -1)       # always keep <last>
    score.masked_fill_(seq == vocab.missing, -1)    # always keep missings
    indices = score.argsort()
    rank = torch.zeros_like(seq)
    rank[torch.arange(len(seq)).unsqueeze(1), indices] = \
        torch.arange(seq.size(1), device=seq.device)
    return rank


def get_known_length_canvas(seq, keep, n, vocab):
    """
    Create the canvas with blanks of known length
    Returns the list of parts necessary to train the model

    Args:
        seq: sequence of tokens
        keep: mask over size of tokens
        vocab: the vocabulary, assuming that blank_0, blank_1, etc. have consecutive indices

    Returns:
        - canvas: list of tokens where consecutive masked out tokens
        have been replaced by the <blank_**> token.
        - blanks: indices in canvas where there are <blank_**> tokens
        - rest: indices in keep_mask where there are False (became blank)
        - loc: indices of how rest relates to blanks
        - lb: size of the blank on the left that has to be opened
    """

    res = get_canvas_cpp.get_known_length_canvas(seq.tolist(), keep.tolist(), n.tolist(), vocab.blanks[0])
    pad = [vocab.pad, -1, -1, -1, -1, -1]
    for i in range(len(res)):
        res[i] = to_tensor(res[i], pad[i], seq.device)
    return res


def get_ins_canvas(seq, keep, n, vocab):
    """Returns canvas, rest, loc"""
    res = get_canvas_cpp.get_insertion_canvas(seq.tolist(), keep.tolist(), n.tolist())
    pad = [vocab.pad, -1, -1]
    for i in range(len(res)):
        res[i] = to_tensor(res[i], pad[i], seq.device)
    return res


def get_canvas(seq, keep, n, vocab):
    res = get_canvas_cpp.get_canvas(seq.tolist(), keep.tolist(), n.tolist(), vocab.blank)
    pad = [vocab.pad, -1, -1, -1, -1, -1]
    for i in range(len(res)):
        res[i] = to_tensor(res[i], pad[i], seq.device)
    return res


def collect(input, index, padding_idx=0):
    """
    Performs a batched index select where index is given for each example
    Args:
        input: tensor of shape (B, T_1, dim_2, dim_3, ...)
        index: tensor of shape (B, T_2)
    Returns:
        tensor of shape (B, T_2, dim_2, dim_3, ...)
    """
    # Add a column of padding_idx at index 0 (of dim 1)
    view = list(input.shape)
    view[1] = 1
    padding_column = input.new_ones(view) * padding_idx
    input = torch.cat([padding_column, input], 1)

    # Expand index to compatible size for gather
    for i in range(2, len(input.shape)):
        index = index.unsqueeze(i)

    view[0] = -1
    view[1] = -1
    index = index.expand(view)
    return torch.gather(input, 1, index + 1)