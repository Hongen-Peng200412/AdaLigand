from __future__ import annotations

from dataclasses import replace

import torch

from matcher.batching import collate_anchor_batch
from matcher.model import Matcher
from matcher.tests.sample_factory import sample as make_sample


def test_phase1_outputs_eight_independent_heads_and_supports_empty_A() -> None:
    model = Matcher(
        phase=1,
        A_node_input_dim=7,
        node_dim=16,
        edge_dim=8,
        repr_dim=32,
        num_heads=4,
        coarse_layers_per_block=1,
        map_channels=(2, 4, 8, 8),
        map_norm_groups=2,
        map_candidate_chunk_size=1,
    )
    model.eval()

    output = model(collate_anchor_batch([make_sample()]))[0]
    assert len(output.block_outputs) == 8
    assert all(head is not None for head in output.block_outputs)
    assert output.block_outputs[-1].O_logit.shape == (2, 2)
    assert output.block_outputs[-1].O_prime.shape == (2, 2)
    assert model.prediction_heads[0].OHead is not model.prediction_heads[1].OHead


def test_phase1_supports_bfloat16_autocast() -> None:
    model = Matcher(
        phase=1,
        A_node_input_dim=7,
        node_dim=16,
        edge_dim=8,
        repr_dim=32,
        num_heads=4,
        coarse_layers_per_block=1,
        map_channels=(2, 4, 8, 8),
        map_norm_groups=2,
        map_candidate_chunk_size=1,
    )
    model.train()

    with torch.autocast(device_type="cpu", dtype=torch.bfloat16):
        output = model(collate_anchor_batch([make_sample()]))[0]
        loss = output.block_outputs[-1].O_logit.sum()
    loss.backward()

    assert output.block_outputs[-1].O_logit.dtype == torch.bfloat16
    assert any(parameter.grad is not None for parameter in model.parameters())


def test_graph_checkpoint_preserves_outputs_and_gradients() -> None:
    kwargs = dict(
        phase=1,
        A_node_input_dim=7,
        node_dim=16,
        edge_dim=8,
        repr_dim=32,
        num_heads=4,
        coarse_layers_per_block=1,
        phase1_blocks=2,
        phase2_blocks=1,
        map_channels=(2, 4, 8, 8),
        map_norm_groups=2,
        map_candidate_chunk_size=1,
        dropout=0.0,
    )
    plain = Matcher(**kwargs, graph_activation_checkpoint=False)
    checkpointed = Matcher(**kwargs, graph_activation_checkpoint=True)
    checkpointed.load_state_dict(plain.state_dict())
    batch = collate_anchor_batch([make_sample()])

    plain_output = plain(batch)[0].block_outputs[-1].O_logit
    checkpointed_output = checkpointed(batch)[0].block_outputs[-1].O_logit
    plain_output.sum().backward()
    checkpointed_output.sum().backward()

    assert torch.allclose(plain_output, checkpointed_output)
    checkpointed_parameters = dict(checkpointed.named_parameters())
    for name, parameter in plain.named_parameters():
        checkpointed_gradient = checkpointed_parameters[name].grad
        if parameter.grad is None and checkpointed_gradient is None:
            continue
        assert parameter.grad is not None
        assert checkpointed_gradient is not None
        assert torch.allclose(parameter.grad, checkpointed_gradient)


def test_packed_graph_encoding_keeps_pdb_outputs_isolated() -> None:
    model = Matcher(
        phase=1,
        A_node_input_dim=7,
        node_dim=16,
        edge_dim=8,
        repr_dim=32,
        num_heads=4,
        coarse_layers_per_block=1,
        dropout=0.0,
        map_channels=(2, 4, 8, 8),
        map_norm_groups=2,
    ).eval()
    left = make_sample()
    right = replace(make_sample(), pdb_id="other", manifest_index=1)

    together = model(collate_anchor_batch([left, right]))
    separate = (
        model(collate_anchor_batch([left]))[0],
        model(collate_anchor_batch([right]))[0],
    )

    for packed_output, single_output in zip(together, separate, strict=True):
        assert torch.allclose(
            packed_output.block_outputs[-1].O_logit,
            single_output.block_outputs[-1].O_logit,
            atol=1.0e-6,
            rtol=1.0e-6,
        )


def test_phase2_freeze_keeps_map_trainable() -> None:
    model = Matcher(
        phase=2,
        A_node_input_dim=7,
        node_dim=16,
        edge_dim=8,
        repr_dim=32,
        num_heads=4,
        coarse_layers_per_block=1,
        map_channels=(2, 4, 8, 8),
        map_norm_groups=2,
    )
    model.freeze_phase1_for_phase2()
    model.train()

    assert not any(parameter.requires_grad for parameter in model.blocks[0].parameters())
    assert not model.blocks[0].training
    assert not model.prediction_heads[0].training
    assert all(parameter.requires_grad for parameter in model.MapBackbone.parameters())
    assert all(parameter.requires_grad for parameter in model.blocks[4].parameters())

    output = model(collate_anchor_batch([make_sample()]))[0]
    output.block_outputs[-1].O_logit.sum().backward()
    assert all(parameter.grad is None for parameter in model.blocks[0].parameters())
    assert any(parameter.grad is not None for parameter in model.MapBackbone.parameters())


def test_phase2_runs_fine_pairs_once_at_final_output() -> None:
    model = Matcher(
        phase=2,
        A_node_input_dim=7,
        node_dim=16,
        edge_dim=8,
        repr_dim=32,
        num_heads=4,
        coarse_layers_per_block=1,
        map_channels=(2, 4, 8, 8),
        map_norm_groups=2,
        fine_pair_chunk_size=2,
        fine_pair_activation_checkpoint=False,
        fine_pair_aux_weight=0.1,
        fine_readout_dim=24,
    )
    model.eval()
    sample = make_sample()
    sample = replace(
        sample,
        ligand_gt_coordinates=(torch.zeros(3, 3), torch.zeros(3, 3)),
        ligand_gt_present=(
            torch.ones(3, dtype=torch.bool),
            torch.ones(3, dtype=torch.bool),
        ),
    )

    output = model(collate_anchor_batch([sample]))[0]

    assert output.block_outputs[:4] == (None, None, None, None)
    assert all(head is not None for head in output.block_outputs[4:])
    assert output.fine_recall_pair_loss.shape == (2, 2, 2)
    assert output.fine_precision_pair_loss.shape == (2, 2, 2)


def test_fine_pair_chunk_and_checkpoint_are_numerically_equivalent() -> None:
    torch.manual_seed(11)
    base = Matcher(
        phase=2,
        A_node_input_dim=7,
        node_dim=16,
        edge_dim=8,
        repr_dim=32,
        num_heads=4,
        coarse_layers_per_block=1,
        dropout=0.0,
        map_channels=(2, 4, 8, 8),
        map_norm_groups=2,
        entity_aux_weight=0.0,
        fine_pair_aux_weight=0.1,
        fine_readout_dim=24,
        fine_pair_chunk_size=None,
        fine_pair_activation_checkpoint=False,
    )
    chunked = Matcher(
        phase=2,
        A_node_input_dim=7,
        node_dim=16,
        edge_dim=8,
        repr_dim=32,
        num_heads=4,
        coarse_layers_per_block=1,
        dropout=0.0,
        map_channels=(2, 4, 8, 8),
        map_norm_groups=2,
        entity_aux_weight=0.0,
        fine_pair_aux_weight=0.1,
        fine_readout_dim=24,
        fine_pair_chunk_size=2,
        fine_pair_activation_checkpoint=False,
    )
    checked = Matcher(
        phase=2,
        A_node_input_dim=7,
        node_dim=16,
        edge_dim=8,
        repr_dim=32,
        num_heads=4,
        coarse_layers_per_block=1,
        dropout=0.0,
        map_channels=(2, 4, 8, 8),
        map_norm_groups=2,
        entity_aux_weight=0.0,
        fine_pair_aux_weight=0.1,
        fine_readout_dim=24,
        fine_pair_chunk_size=2,
        fine_pair_activation_checkpoint=True,
    )
    chunked.load_state_dict(base.state_dict())
    checked.load_state_dict(base.state_dict())
    sample = replace(
        make_sample(),
        ligand_gt_coordinates=(torch.zeros(3, 3), torch.ones(3, 3)),
        ligand_gt_present=(
            torch.ones(3, dtype=torch.bool),
            torch.ones(3, dtype=torch.bool),
        ),
    )
    batch = collate_anchor_batch([sample])

    def run(model: Matcher) -> tuple[torch.Tensor, torch.Tensor, dict[str, torch.Tensor]]:
        model.freeze_phase1_for_phase2()
        model.train()
        output = model(batch)[0]
        final = output.block_outputs[-1]
        value = (
            final.O_logit.sum()
            + final.O_prime.sum()
            + output.fine_recall_pair_loss.sum()
            + output.fine_precision_pair_loss.sum()
        )
        value.backward()
        gradients = {
            name: parameter.grad.detach().clone()
            for name, parameter in model.named_parameters()
            if parameter.grad is not None
        }
        return final.O_logit.detach(), output.fine_recall_pair_loss.detach(), gradients

    plain_O, plain_aux, plain_grad = run(base)
    for model in (chunked, checked):
        other_O, other_aux, other_grad = run(model)
        assert torch.allclose(plain_O, other_O, atol=1.0e-6, rtol=1.0e-6)
        assert torch.allclose(plain_aux, other_aux, atol=1.0e-6, rtol=1.0e-6)
        assert other_grad.keys() == plain_grad.keys()
        for name in plain_grad:
            assert torch.allclose(
                plain_grad[name], other_grad[name], atol=2.0e-5, rtol=2.0e-5
            ), name
