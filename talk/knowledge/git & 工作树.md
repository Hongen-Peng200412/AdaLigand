# Git 与工作树

本文解释 Git 的提交、分支、工作树，以及 Codex 桌面应用中的“在新工作树中继续”。目标是让没有参与此前对话的人，仅阅读本文就能理解：

- 为什么同一个 Git 仓库可以同时出现多个项目文件夹；
- 为什么某个分支不能同时在两个文件夹中检出；
- Codex 新建工作树时，聊天、文件和 Git 分支分别发生了什么；
- 一个工作树中的已提交和未提交改动怎样进入另一个工作树；
- 截图中的 `already used by worktree` 错误到底属于哪一类问题。

本文使用的“工作树”是 Git 的正式术语，指一个实际存在于磁盘上的项目文件夹及其对应的 Git 状态。本文不把“工作树”与“分支”当作同一个东西。

## 一、先记住四个概念

### 1. 仓库

Git 仓库是保存项目历史的结构。对普通项目来说，项目文件夹中通常有一个 `.git` 目录。`.git` 中保存提交对象、分支引用、标签、配置和工作树登记信息。

仓库不等于某一个项目文件夹。使用 Git worktree 后，一个仓库可以对应多个项目文件夹。

### 2. 提交

提交（commit）是某一时刻项目文件的完整快照，并带有提交说明和父提交。提交由哈希值标识，例如：

```text
799293c584586278ab5f313ce435533e2e1c3ff1
```

提交本身不是一个会自动变化的标签。新的提交会产生新的哈希值。

可以把提交想成项目历史中的一张“定格照片”：

```text
提交 A —— 提交 B —— 提交 C
```

### 3. 分支

分支是一个指向某个提交的名称。例如：

```text
main       -> 提交 C
feature    -> 提交 B
```

分支不是一个文件夹，也不是一套独立的代码副本。提交新代码后，当前分支名称会移动到新的提交：

```text
提交 A —— 提交 B —— 提交 C —— 提交 D
                              ↑
                           feature
```

因此，分支是“会移动的提交名称”。

### 4. 工作树

工作树是一个真正存在的文件夹，例如：

```text
C:\Users\15919\Desktop\AdaLigand
```

这个文件夹中有当前检出的源代码、配置和测试文件。工作树还拥有自己的：

- `HEAD`：记录它当前检出哪个分支或哪个提交；
- `index`：Git 暂存区，记录下一次提交准备包含的文件状态；
- 未提交文件修改。

一个仓库可以拥有一个主工作树和多个链接工作树。链接工作树通常由 `git worktree add` 或 Codex 创建。

## 二、分支、提交和工作树如何组合

假设历史是：

```text
提交 A —— 提交 B —— 提交 C
```

现在有两个分支：

```text
main    -> 提交 C
learn   -> 提交 B
```

可以建立两个工作树：

```text
文件夹 1：检出 main，文件内容对应提交 C
文件夹 2：检出 learn，文件内容对应提交 B
```

这两个工作树共享同一个 Git 仓库历史，但文件可以分别修改。

还可以有两个不同分支同时指向同一个提交：

```text
Learn/CUMULATIVE                    -> 提交 X
Learn/data-preprocessing-maintenance -> 提交 X
```

这两个分支名称不同，所以可以放在两个工作树中，即使它们当前指向相同提交。

## 三、为什么同一个分支不能放在两个工作树

假设分支名称是 `feature`。

如果两个文件夹同时检出它：

```text
文件夹 1：feature
文件夹 2：feature
```

两个文件夹都会声称自己是 `feature` 的当前工作副本。

如果文件夹 1 提交，`feature` 会移动到新提交；如果文件夹 2 也提交，`feature` 又会被另一次操作移动。两个文件夹中的文件还可能各自不同，Git 无法确定哪个文件夹才是这个分支的唯一工作副本。

因此 Git 默认阻止第二个工作树检出同一个分支。这是“分支占用冲突”，不是“代码内容冲突”。

Git 官方提供了 `--ignore-other-worktrees` 选项强行绕过保护，但这只是允许同一个分支出现在多个工作树，并不会解决两个文件夹同时提交、重置或合并造成的歧义。正常工作不应使用它。[Git `switch` 官方文档](https://git-scm.com/docs/git-switch)

## 四、工作树内部实际共享什么、分开什么

Git 官方文档说明，链接工作树共享仓库的大部分元数据，但每个工作树有自己的 `HEAD`、`index` 等状态。[Git `worktree` 官方文档](https://git-scm.com/docs/git-worktree.html)

### 共享内容

- 提交对象；
- 普通分支引用，例如 `refs/heads/Learn/CUMULATIVE`；
- 标签；
- 通常共享的 Git 配置；
- 仓库的提交图。

### 独立内容

- 工作树中的实际文件；
- 当前工作树的 `HEAD`；
- 当前工作树的暂存区 `index`；
- 未提交修改；
- 工作树专用配置。

在链接工作树中，顶层的 `.git` 通常不是完整目录，而是一个指向主仓库管理目录的文本文件。AdaLigand 当前的 A–G 实现工作树中，这个文件指向：

```text
C:/Users/15919/Desktop/AdaLigand/.git/worktrees/AdaLigand-a-g-maintenance
```

该管理目录中的 `HEAD` 指向：

```text
refs/heads/codex/adaligand-data-preprocessing-maintenance
```

这正是 Git 知道“这个分支已经被那个工作树占用”的原因。一般不应手工修改这些内部文件，应使用 `git worktree` 命令。

## 五、当前 AdaLigand 仓库的实际工作树

以下是 2026-07-23 在本机用 `git worktree list --verbose` 核验的状态。路径状态会随以后操作变化，这张表不是永久契约。

| 工作树文件夹 | 当前提交 | 当前分支或状态 | 作用 |
| --- | --- | --- | --- |
| `C:\Users\15919\Desktop\AdaLigand` | `799293c` | `Learn/CUMULATIVE` | 当前主工作区 |
| `C:\Users\15919\.codex\worktrees\e096\AdaLigand` | `817940a` | detached HEAD | Codex 创建的未绑定分支工作树 |
| `C:\Users\15919\.codex\worktrees\e096\AdaLigand-a-g-learn` | `799293c` | `Learn/data-preprocessing-maintenance` | A–G 学习线工作树 |
| `C:\Users\15919\.codex\worktrees\e096\AdaLigand-a-g-maintenance` | `0442681` | `codex/adaligand-data-preprocessing-maintenance` | A–G 实现线工作树 |

因此，截图中的错误：

```text
fatal: 'codex/adaligand-data-preprocessing-maintenance'
is already used by worktree at
'C:\Users\15919\.codex\worktrees\e096\AdaLigand-a-g-maintenance'
```

可以翻译为：

> 你正在当前主工作区中尝试检出 A–G 实现分支，但这个分支已经在 `AdaLigand-a-g-maintenance` 文件夹中检出，所以 Git 拒绝第二次检出。

它不是说这个分支不存在，也不是说当前代码已经产生了合并冲突。

## 六、Codex 的“在新工作树中继续”

Codex 官方文档说明，桌面版 Codex 的工作树底层使用 Git worktree。默认流程是：

1. 选择一个 Git 项目；
2. 选择一个起始分支或起始提交；
3. Codex 在 `$CODEX_HOME/worktrees` 下建立独立文件夹；
4. 将起始提交的文件放入该文件夹；
5. 如果起始工作区有未提交修改，Codex 会把这些修改应用到新工作树；
6. 默认使用 detached HEAD，而不是立即占用一个正式分支；
7. 需要长期保留时，可以在该工作树中创建正式分支。

你的本机路径：

```text
C:\Users\15919\.codex\worktrees\e096\
```

与 Codex 官方说明的默认工作树位置一致。[Codex Worktrees 官方文档](https://learn.chatgpt.com/docs/environments/git-worktrees)

### detached HEAD 是什么

普通检出状态是：

```text
HEAD -> refs/heads/某个分支
```

detached HEAD 则是：

```text
HEAD -> 某个具体提交
```

它表示当前文件夹直接停在某个提交上，没有占用分支名称。这样 Codex 可以同时创建多个独立工作树，而不必让所有工作树争抢正式分支。

如果在 detached HEAD 中产生提交，但没有随后创建分支或保存提交哈希，未来可能不容易从分支列表中找到它。因此长期工作通常应在明确的任务分支上进行。

### “继续”与“汇入”不是同一件事

Codex 的“在新工作树中继续”主要解决的是：

```text
让聊天继续在另一个文件夹和另一个 Git 状态中工作
```

它不等于：

```text
自动把该工作树的代码合并回当前主工作区
```

Codex 官方还提供 Handoff，用于把聊天和代码从 Local 转移到 Worktree，或从 Worktree 转移回 Local。Handoff 会执行必要的 Git 操作，但具体是否产生合并、切换分支或应用未提交修改，应以该次操作的实际结果为准，而不能把它简单理解成复制文件。[Codex Worktrees 官方文档](https://learn.chatgpt.com/docs/environments/git-worktrees)

## 七、改动如何从一个工作树进入另一个工作树

### 已提交改动

假设 A–G 实现工作树产生提交：

```text
0442681
```

因为所有工作树共享同一个 Git 仓库，该提交会立即存在于仓库历史中。其他工作树可以查看：

```powershell
git show 0442681
git log --all
```

但是，其他工作树的实际文件不会自动变成 `0442681` 的内容。要把提交纳入另一个分支，需要明确执行一种 Git 历史操作：

- `git merge`：把另一条历史合并进当前分支；
- `git cherry-pick`：把指定提交复制为当前分支上的新提交；
- 快进移动：当前分支没有额外提交时，直接把分支名称移动到目标提交；
- Codex Handoff：让 Codex 按其工作流处理 Local 与 Worktree 的转移。

### 未提交改动

未提交改动只存在于产生它的工作树的文件和暂存区中：

```text
工作树 A 修改了文件
工作树 B 不会自动看到这个修改
```

要转移未提交改动，必须使用 Handoff、提交后再合并，或者由用户明确选择其他迁移方式。不能只因为两个工作树来自同一个仓库，就假定未提交文件会自动同步。

## 八、两类完全不同的“冲突”

### 1. 分支占用冲突

典型错误：

```text
already used by worktree
```

含义：同一个分支已经被另一个工作树检出。此时 Git 通常还没有比较文件内容。

解决方式：

- 继续使用已经占用该分支的工作树；
- 使用 Codex Handoff；
- 确认旧工作树已经干净后，使用 `git worktree remove <路径>` 删除旧工作树，再在当前工作树检出分支；
- 或让旧工作树切换到另一个分支或 detached HEAD。

### 2. 文件内容冲突

这发生在合并、cherry-pick、Handoff 或带本地修改的分支切换过程中。例如两个来源都修改了同一个文件的同一段内容。

此时 Git 会显示冲突标记，并要求人类或 agent 决定保留哪一部分。它与“分支已经被占用”是两个不同阶段的问题。

## 九、如何安全检查和清理工作树

查看所有工作树及其分支：

```powershell
git worktree list --porcelain
```

查看当前文件夹的分支和未提交修改：

```powershell
git status --short --branch
```

删除一个已经确认干净的链接工作树：

```powershell
git worktree remove "C:\明确确认过的工作树路径"
```

这个命令删除链接工作树及其登记信息，但不会因为删除工作树而自动删除该分支的提交历史。Git 默认拒绝删除有未提交修改的工作树；不要使用 `--force` 隐藏尚未保存的修改。[Git 官方 worktree 文档](https://git-scm.com/docs/git-worktree.html)

如果工作树文件夹已经被外部手段删除，但 Git 仍然保留旧登记信息，可以先使用只读检查：

```powershell
git worktree prune --dry-run --verbose
```

不要把 `git worktree prune` 当作普通分支删除命令；它只清理已经失效的工作树登记。

## 十、适合本项目的长期工作方式

建议保持下面的角色分工：

```text
主工作区：Learn/CUMULATIVE
实现工作树：codex/<具体任务名>
学习工作树：Learn/<具体主题>
```

每个分支只在一个工作树中检出。新的实现任务从最新的 `Learn/CUMULATIVE` 建立新的实现分支；实现线和学习线完成等价核验后，才推进 `Learn/CUMULATIVE`。

开始任务、切换分支或删除工作树前，先执行：

```powershell
git worktree list --porcelain
git status --short --branch
```

这套方式可以长期并行运行 Codex 任务，但不能让两个 Codex 聊天同时修改同一个分支。

## 十一、当前仓库实例的结论

2026-07-23 的本地核验结论是：

- 主工作区已经位于 `Learn/CUMULATIVE@799293c`；
- A–G 学习线位于 `C:\Users\15919\.codex\worktrees\e096\AdaLigand-a-g-learn`；
- A–G 实现线位于 `C:\Users\15919\.codex\worktrees\e096\AdaLigand-a-g-maintenance`；
- 截图中的错误是尝试在主工作区再次检出 A–G 实现分支造成的分支占用冲突；
- 这不表示 A–G 代码损坏，也不表示 Git 历史已经合并失败；
- 如果 A–G 实现工作树已经不再需要，必须先确认它干净，再决定是否删除该工作树；
- 即使删除该工作树，`codex/adaligand-data-preprocessing-maintenance` 分支和提交仍需单独决定是否保留。

## 十二、Q&A

### Q1：工作树是不是 Git 分支的一个副本？

不完全是。

工作树是一个实际文件夹，里面有某个提交展开后的文件。分支只是一个指向提交的名称。一个工作树可以检出一个分支，也可以处于 detached HEAD；一个分支不能同时被两个工作树正常检出。

### Q2：两个工作树是不是完全互不相关？

不是。它们共享提交、分支名称和 Git 历史，但文件、`HEAD`、暂存区和未提交修改各自独立。

### Q3：如果两个分支指向同一个提交，为什么还要分成两个工作树？

分支指向同一个提交只说明它们当前起点相同。之后一个分支可以继续提交而另一个分支不动。把它们放在不同工作树中，可以同时阅读、测试或修改，而不互相覆盖文件。

### Q4：Codex 新工作树里的代码什么时候会回到主工作区？

不会因为创建工作树而自动回来。需要使用 Codex Handoff，或者在 Git 中通过合并、cherry-pick、快进等方式把已提交历史纳入目标分支。未提交修改还需要额外迁移。

### Q5：为什么 Git Graph 能看到某个提交，但当前文件夹没有对应代码？

Git Graph 显示的是共享的提交历史和分支引用；当前文件夹只显示它自己检出的分支和文件。看到提交不等于当前工作树已经切换到该提交。

### Q6：删除工作树会不会删除分支？

`git worktree remove` 删除的是链接工作树和它的登记信息。它不会自动执行 `git branch -d`，所以不应把“删除工作树”和“删除分支”混为一谈。分支是否继续保留，应单独检查和决定。

### Q7：能不能直接使用 `git switch --ignore-other-worktrees`？

技术上可以，但它会允许同一个分支同时被多个工作树检出，破坏 Git 默认提供的唯一工作副本保护。除非已经明确设计了这种高级用法并能保证不会并行提交，否则不应使用。

### Q8：当前截图里的错误要不要立刻修复？

如果你只是继续使用 `Learn/CUMULATIVE`，不需要修复；错误只在你尝试检出 A–G 实现分支时出现。如果你确实要在主工作区使用 A–G 实现分支，就先确认 `AdaLigand-a-g-maintenance` 不再运行且工作树干净，再使用 Handoff 或 `git worktree remove` 释放它。

## 十三、后续问答（持续追加）

以后关于 Git、工作树、Codex 任务转移、分支汇入、提交组织或本项目双线历史的问题，继续追加在本节。每次追加使用以下格式：

```markdown
### Q：具体问题

### A：基于当前本地核验和官方资料的回答

### 当前仓库证据

- 命令、路径、分支或提交哈希

### 官方资料

- 相关官方文档链接
```

## 官方资料

- [Git `git-worktree` 官方文档](https://git-scm.com/docs/git-worktree.html)
- [Git `git-switch` 官方文档](https://git-scm.com/docs/git-switch)
- [Codex Worktrees 官方文档](https://learn.chatgpt.com/docs/environments/git-worktrees)
