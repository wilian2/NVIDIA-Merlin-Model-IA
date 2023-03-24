from copy import deepcopy
from functools import reduce
from typing import Callable, Dict, Iterator, List, Union

import torch
from torch import nn
from torch._jit_internal import _copy_to_script_wrapper

from merlin.models.torch.base import NoOp, TabularBlock
from merlin.models.torch.transforms.aggregation import SumResidual
from merlin.models.torch.utils.module_utils import apply
from merlin.schema import Schema, Tags


class ParallelBlock(TabularBlock):
    """
    A block that processes inputs in parallel through multiple layers and returns their outputs.

    Parameters
    ----------
    *inputs : Union[nn.Module, Dict[str, nn.Module]]
        Variable length list of PyTorch modules or dictionaries of PyTorch modules.
    pre : Callable, optional
        Preprocessing function to apply on inputs before processing.
    post : Callable, optional
        Postprocessing function to apply on outputs after processing.
    aggregation : Callable, optional
        Aggregation function to apply on outputs.
    """

    def __init__(
        self, *inputs: Union[nn.Module, Dict[str, nn.Module]], pre=None, post=None, aggregation=None
    ):
        super().__init__(pre, post, aggregation)

        if isinstance(inputs, tuple) and len(inputs) == 1 and isinstance(inputs[0], (list, tuple)):
            inputs = inputs[0]

        if all(isinstance(x, dict) for x in inputs):
            _parallel_dict = reduce(lambda a, b: dict(a, **b), inputs)
        elif all(isinstance(x, nn.Module) for x in inputs):
            _parallel_dict = {i: m for i, m in enumerate(inputs)}
        else:
            raise ValueError(f"Invalid input. Got: {inputs}")

        self.parallel_dict = _parallel_dict
        for key, val in _parallel_dict.items():
            self.add_module(str(key), val)

        if all(hasattr(m, "schema") for m in _parallel_dict.values()):
            self.schema = reduce(
                lambda a, b: a + b, [m.schema for m in _parallel_dict.values()]
            )  # type: ignore

    def forward(self, inputs, **kwargs):
        """
        Process inputs through the parallel layers.

        Parameters
        ----------
        inputs : Tensor
            Input tensor to process through the parallel layers.
        **kwargs : dict
            Additional keyword arguments for layer processing.

        Returns
        -------
        outputs : dict
            Dictionary containing the outputs of the parallel layers.
        """
        outputs = {}

        for name, module in self.parallel_dict.items():
            module_inputs = inputs  # TODO: Add filtering when adding schema
            out = apply(module, module_inputs, **kwargs)
            if not isinstance(out, dict):
                out = {name: out}
            outputs.update(out)

        return outputs

    def select_by_name(self, names) -> "ParallelBlock":
        if self.schema is not None and self.schema == self.schema.select_by_name(names):
            return self

        selected_branches = {}
        selected_schemas = Schema()

        for name, branch in self.parallel_dict.items():
            branch_has_schema = hasattr(branch, "schema")
            if not branch_has_schema:
                continue
            if not hasattr(branch, "select_by_name"):
                raise AttributeError(
                    f"This ParallelBlock does not support select_by_tag because "
                    f"{branch.__class__} does not support select_by_tag. Consider "
                    "implementing a select_by_name in an extension of "
                    f"{branch.__class__}."
                )
            selected_branch = branch.select_by_name(names)
            if not selected_branch:
                continue
            selected_branches[name] = selected_branch
            selected_schemas += selected_branch.schema

        return ParallelBlock(
            selected_branches,
            post=self.post,
            pre=self.pre,
            aggregation=self.aggregation,
        )

    def select_by_tag(self, tags: Union[str, Tags, List[Union[str, Tags]]]) -> "ParallelBlock":
        """Select branches by tags and return a new ParallelBlock.

        This method will return a ParallelBlock instance with all the branches that
        have at least one feature that matches any of the tags provided.

        For example, this method can be useful when a ParallelBlock has both item and
        user features in a two-tower model or DLRM, and we want to select only the item
        or user features.

        >>> all_inputs = TabularInputBlock(schema)  # TabularInputBlock is a ParallelBlock
        >>> item_inputs = all_inputs.select_by_tag(Tags.ITEM)
        ['continuous', 'embeddings']
        >>> item_inputs.schema["continuous"].column_names
        ['item_recency']
        >>> item_inputs.schema["embeddings"].column_names
        ['item_id', 'item_category', 'item_genres']

        Parameters
        ----------
        tags: str or Tags or List[Union[str, Tags]]
             List of tags that describe which blocks to match

        Returns
        -------
        ParallelBlock
        """
        if self.schema is not None and self.schema == self.schema.select_by_tag(tags):
            return self

        if not isinstance(tags, (list, tuple)):
            tags = [tags]

        selected_branches = {}
        selected_schemas = Schema()

        for name, branch in self.parallel_dict.items():
            branch_has_schema = hasattr(branch, "schema")
            if not branch_has_schema:
                continue
            if not hasattr(branch, "select_by_tag"):
                raise AttributeError(
                    f"This ParallelBlock does not support select_by_tag because "
                    f"{branch.__class__} does not support select_by_tag. Consider "
                    "implementing a select_by_tag in an extension of "
                    f"{branch.__class__}."
                )
            selected_branch = branch.select_by_tag(tags)
            if not selected_branch:
                continue
            selected_branches[name] = selected_branch
            selected_schemas += selected_branch.schema

        return ParallelBlock(
            selected_branches,
            post=self.post,
            pre=self.pre,
            aggregation=self.aggregation,
        )

    def items(self):
        return self.parallel_dict.items()

    def keys(self):
        return self.parallel_dict.keys()

    def values(self):
        return self.parallel_dict.values()

    @property
    def first(self) -> nn.Module:
        return next(iter(self.parallel_dict.values()))

    @_copy_to_script_wrapper
    def __len__(self) -> int:
        return len(self.parallel_dict)

    @_copy_to_script_wrapper
    def __iter__(self) -> Iterator[nn.Module]:
        return iter(self.parallel_dict.values())

    @_copy_to_script_wrapper
    def __getitem__(self, key) -> nn.Module:
        return self.parallel_dict[key]

    def __bool__(self) -> bool:
        return bool(self.parallel_dict)


class WithShortcut(ParallelBlock):
    """Parallel block for a shortcut connection.

    This block will apply `module` to it's inputs  outputs the following:
    ```python
    {
        module_output_name: module(inputs),
        shortcut_output_name: inputs
    }
    ```

    Parameters:
    -----------
    module : nn.Module
        The input module.
    aggregation : nn.Module or None, optional
        Optional module that aggregates the dictionary into a single tensor.
        Defaults to None.
    post : nn.Module or None, optional
        Optional module that takes in a dict of tensors and outputs a transformed dict of tensors.
        Defaults to None.
    block_outputs_name : str or None, optional
        The name of the output dictionary of the parallel block.
        Defaults to the name of the input module.
    **kwargs : dict
        Additional keyword arguments to be passed to the superclass ParallelBlock.


    """

    def __init__(
        self,
        module: nn.Module,
        *,
        aggregation=None,
        post=None,
        module_output_name="output",
        shortcut_output_name="shortcut",
        **kwargs,
    ):
        super().__init__(
            {module_output_name: module, shortcut_output_name: NoOp()},
            post=post,
            aggregation=aggregation,
            **kwargs,
        )


class ResidualBlock(WithShortcut):
    """
    Residual block for a shortcut connection with a sum operation and optional activation.

    Parameters
    ----------
    module : nn.Module
        The input module.
    activation : Union[Callable[[torch.Tensor], torch.Tensor], str], optional
        Activation function to be applied after the sum operation.
        It can be a callable or a string representing a standard activation function.
        Defaults to None.
    post : nn.Module or None, optional
        Optional module that takes in a dict of tensors and outputs a transformed dict of tensors.
        Defaults to None.
    **kwargs : dict
        Additional keyword arguments to be passed to the superclass WithShortcut.

    Examples
    --------
    >>> linear = nn.Linear(5, 3)
    >>> residual_block = ResidualBlock(linear, activation=nn.ReLU())

    """

    def __init__(
        self,
        module: nn.Module,
        *,
        activation: Union[Callable[[torch.Tensor], torch.Tensor], str] = None,
        post=None,
        **kwargs,
    ):
        super().__init__(
            module,
            post=post,
            aggregation=SumResidual(activation=activation),
            **kwargs,
        )


class SequentialBlock(nn.Sequential):
    """A sequential container.
    This class extends PyTorch's Sequential class with additional functionalities.

    Parameters
    ----------
    *args : nn.Module
        Variable-length list of modules to be added sequentially.
    pre : nn.Module, optional
        An optional module to be applied before the input is passed to the sequential modules.
    post : nn.Module, optional
        An optional module to be applied after the output is obtained from the sequential modules.

    Methods
    -------
    append_with_shortcut(module, post=None, aggregation=None)
        Appends a module with a shortcut connection to the sequential block.
    append_with_residual(module, activation=None, **kwargs)
        Appends a module with a residual connection to the sequential block.
    append_branch(*branches, post=None, aggregation=None, **kwargs)
        Appends a branch of parallel modules to the sequential block.
    repeat(num=1, copies=True)
        Repeats the sequential block a specified number of times.
    repeat_in_parallel(num=1, prefix=None, names=None, post=None, aggregation=None,
        copies=True, shortcut=False, **kwargs)
        Repeats the sequential block in parallel a specified number of times.
    """

    def __init__(self, *args, pre=None, post=None):
        super().__init__(*args)
        self.pre = pre
        self.post = post

    def __call__(self, inputs, *args, model_context=None, **kwargs):
        if self.pre is not None:
            inputs = apply(self.pre, inputs, *args, model_context=model_context, **kwargs)
            outputs = super().__call__(inputs, model_context=model_context)
        else:
            outputs = super().__call__(inputs, *args, model_context=model_context, **kwargs)

        if self.post is not None:
            outputs = self.post(outputs)

        return outputs

    def forward(self, input, *args, model_context=None, **kwargs):
        for i, module in enumerate(self):
            if i == 0:
                input = apply(module, input, *args, model_context=model_context, **kwargs)
            else:
                input = apply(module, input, model_context=model_context)
        return input

    def append_with_shortcut(
        self,
        module: nn.Module,
        *,
        post=None,
        aggregation=None,
    ) -> "SequentialBlock":
        """Appends a module with a shortcut connection to the sequential block.

        Parameters
        ----------
        module : nn.Module
            The module to be added with a shortcut connection.
        post : nn.Module, optional
            An optional module that takes in a dict of tensors and outputs
            a transformed dict of tensors.
        aggregation : nn.Module, optional
            An optional module that aggregates the dictionary output of the
            parallel block into a single tensor.

        Returns
        -------
        SequentialBlock
            The updated sequential block with the appended module.
        """
        return self.append(WithShortcut(module, post=post, aggregation=aggregation))

    def append_with_residual(
        self, module: nn.Module, *, activation=None, **kwargs
    ) -> "SequentialBlock":
        """Appends a module with a residual connection to the sequential block.

        Parameters
        ----------
        module : nn.Module
            The module to be added with a residual connection.
        activation : callable or str, optional
            The activation function to be applied after the residual connection.

        Returns
        -------
        SequentialBlock
            The updated sequential block with the appended module.
        """
        return self.append(ResidualBlock(module, activation=activation, **kwargs))

    def append_branch(
        self,
        *branches: Union[nn.Module, Dict[str, nn.Module]],
        post=None,
        aggregation=None,
        **kwargs,
    ) -> "SequentialBlock":
        """Appends a branch of parallel modules to the sequential block.

        Parameters
        ----------
        *branches : nn.Module
            Variable-length list of modules to be added in parallel.
        post : nn.Module, optional
            An optional module to be applied after the output is obtained
            from the parallel branches.
        aggregation : nn.Module, optional
            An optional module that aggregates the outputs from the parallel
            branches into a single tensor.

        Returns
        -------
        SequentialBlock
            The updated sequential block with the appended branch of parallel modules.
        """
        return self.append(ParallelBlock(*branches, post=post, aggregation=aggregation, **kwargs))

    def repeat(self, num: int = 1, copies=True) -> "SequentialBlock":
        """
        Repeats the sequential block a specified number of times.

        Parameters
        ----------
        num : int, optional
            The number of times to repeat the sequential block. Default is 1.
        copies : bool, optional
            Whether to create deep copies of the modules for each repetition. Default is True.

        Returns
        -------
        SequentialBlock
            The repeated sequential block.
        """
        self_modules = list(self._modules.values())
        output_modules = [*self_modules]
        for _ in range(num):
            if copies:
                repeated = deepcopy(self_modules)
                for m in repeated:
                    if hasattr(m, "reset_parameters"):
                        m.reset_parameters()
            else:
                repeated = self_modules
            output_modules.extend(repeated)

        return SequentialBlock(*output_modules, pre=self.pre, post=self.post)

    def repeat_in_parallel(
        self,
        num: int = 1,
        prefix=None,
        names=None,
        post=None,
        aggregation=None,
        copies=True,
        shortcut=False,
        **kwargs,
    ) -> "ParallelBlock":
        """
        Repeats the sequential block in parallel a specified number of times.

        Parameters
        ----------
        num : int, optional
            The number of times to repeat the sequential block in parallel. Default is 1.
        prefix : str, optional
            A string prefix to be used for naming the repeated branches if names are not provided.
        names : list of str, optional
            A list of names for the repeated branches.
            If not provided, the branches will be named using the prefix and an integer index.
        post : nn.Module, optional
            An optional module to be applied after the output is obtained
            from the parallel branches.
        aggregation : nn.Module, optional
            An optional module that aggregates the outputs from the
            parallel branches into a single tensor.
        copies : bool, optional
            Whether to create deep copies of the modules for each repetition. Default is True.
        shortcut : bool, optional
            Whether to include a shortcut connection in the parallel branches. Default is False.

        Returns
        -------
        ParallelBlock
            The parallel block containing the repeated sequential blocks.
        """
        repeated = {}
        iterator = names if names else range(num)
        self_modules = list(self._modules.values())

        if not names and prefix:
            iterator = [f"{prefix}{num}" for num in iterator]
        for name in iterator:
            branch = self
            if copies:
                branch_modules = deepcopy(self_modules)
                for m in branch_modules:
                    if hasattr(m, "reset_parameters"):
                        m.reset_parameters()
                branch = SequentialBlock(*branch_modules, pre=self.pre, post=self.post)
            repeated[str(name)] = branch

        if shortcut:
            repeated["shortcut"] = NoOp()

        return ParallelBlock(repeated, post=post, aggregation=aggregation, **kwargs)