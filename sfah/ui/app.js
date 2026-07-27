const state = {
  selectedArtifact: "discovery",
  status: null,
  busy: false,
};

const artifactLabels = {
  discovery: "理解目标",
  spec: "规格说明",
  plan: "执行计划",
  tasks: "任务拆解",
};

const stages = [
  ["INIT", "尚未开始"],
  ["DISCOVERED", "已理解目标"],
  ["SPEC_DRAFTED", "规格草稿"],
  ["SPEC_APPROVED", "规格已确认"],
  ["PLAN_DRAFTED", "计划草稿"],
  ["PLAN_APPROVED", "计划已确认"],
  ["TASKS_READY", "任务已准备"],
];

const stageOrder = Object.fromEntries(stages.map(([key], index) => [key, index]));

const statusLabels = {
  TODO: "待办",
  WIP: "进行中",
  DONE: "已完成",
  BLOCKED: "被阻塞",
};

const priorityLabels = {
  REQUIRED: "必须做",
  RECOMMENDED: "建议做",
  OPTIONAL: "可选做",
};

const eventLabels = {
  task_created: "创建任务",
  task_updated: "更新任务",
  task_completed: "完成任务",
  execution_artifact_saved: "保存执行记录",
  artifact_saved_from_ui: "保存工件",
  artifact_rolled_back_from_ui: "恢复历史版本",
  ui_discovery_generated: "理解目标",
  ui_spec_generated: "生成规格说明",
  ui_spec_approved: "确认规格说明",
  ui_plan_generated: "生成执行计划",
  ui_plan_approved: "确认执行计划",
  ui_tasks_generated: "拆解任务",
  ui_execute_completed: "执行任务",
  ui_review_plan: "检查计划",
  ui_llm_step_saved: "保存模型设置",
  ui_llm_step_reset: "恢复默认模型",
  ui_auto_run_started: "启动全自动运行",
  ui_auto_run_finished: "结束全自动运行",
};

const guidance = {
  INIT: ["先输入目标", "从一句真实需求开始。这里会先理解范围、假设、风险和待确认问题。"],
  DISCOVERED: ["检查目标理解", "请看看理解目标是否准确。确认后可以生成规格说明，把需求变成可审阅的交付契约。"],
  SPEC_DRAFTED: ["确认规格说明", "请编辑规格说明，特别是范围内、范围外和验收标准。确认后才能进入执行计划。"],
  SPEC_APPROVED: ["生成执行计划", "规格已经确认。下一步是把它变成可执行计划，并提前暴露风险和验证方式。"],
  PLAN_DRAFTED: ["确认执行计划", "请检查计划是否符合你的真实意图。确认后系统才会拆解任务。"],
  PLAN_APPROVED: ["拆解任务", "计划已经确认。现在可以拆成可验收的小任务，每个任务都应该有边界和依赖。"],
  TASKS_READY: ["执行与检查", "任务已经准备好。你可以执行待办任务，也可以继续编辑任务工件再保存。"],
};

function $(selector) {
  return document.querySelector(selector);
}

function setBusy(isBusy) {
  state.busy = isBusy;
  document.querySelectorAll("button").forEach((button) => {
    button.disabled = isBusy;
  });
}

function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => el.classList.remove("show"), 2400);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!payload.ok) {
    throw new Error(payload.message || "操作失败");
  }
  return payload.data;
}

async function refreshStatus() {
  state.status = await api("/api/status");
  renderStatus();
  renderTasks();
  renderEvents();
  renderSnapshots();
  renderModelSteps();
  renderAutoStatus();
}

async function loadArtifact(name = state.selectedArtifact) {
  state.selectedArtifact = name;
  const data = await api(`/api/artifact?name=${encodeURIComponent(name)}`);
  $("#artifactTitle").textContent = artifactLabels[name] || name;
  $("#artifactPath").textContent = data.exists ? data.path : "这个工件还没有生成";
  $("#artifactEditor").value = data.content || "";
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.artifact === name);
  });
}

function renderStatus() {
  const data = state.status;
  const workflow = data.workflow || {};
  const stage = workflow.stage || "INIT";
  const label = data.stage_label || stage;
  const goal = workflow.goal || "还没有设置目标";
  $("#projectTitle").textContent = goal;
  $("#stageBadge").textContent = label;
  $("#profileBadge").textContent = `模型：${data.provider?.profile || "未设置"}`;
  $("#goalInput").value = workflow.goal || $("#goalInput").value;
  $("#contextInput").value = workflow.context || $("#contextInput").value;
  $("#metricTotal").textContent = data.stats?.total ?? 0;
  $("#metricTodo").textContent = data.stats?.todo ?? 0;
  $("#metricDone").textContent = data.stats?.done ?? 0;

  const [title, text] = guidance[stage] || ["继续推进", "请选择下一步操作。"];
  $("#inspectorTitle").textContent = title;
  $("#inspectorText").textContent = text;

  const currentIndex = stageOrder[stage] ?? 0;
  $("#steps").innerHTML = stages
    .map(([key, text], index) => {
      const classes = ["step"];
      if (index < currentIndex) classes.push("done");
      if (index === currentIndex) classes.push("current");
      return `<button class="${classes.join(" ")}" data-stage="${key}">
        <span class="step-index">${index + 1}</span>
        <span>${text}</span>
      </button>`;
    })
    .join("");
}

function renderTasks() {
  const tasks = state.status?.tasks || [];
  $("#taskHint").textContent = tasks.length ? `${tasks.length} 个任务` : "从计划拆解后显示";
  $("#taskList").innerHTML = tasks.length
    ? tasks
        .map((task) => {
          const criteria = (task.acceptance_criteria || []).slice(0, 2).map((item) => `<span class="pill">${escapeHtml(item)}</span>`).join("");
          return `<article class="task-item">
            <label class="task-title-line">
              <input type="checkbox" class="task-check" value="${task.id}" ${task.status !== "TODO" ? "disabled" : ""} />
              <strong>${task.id}. ${escapeHtml(task.title)}</strong>
            </label>
            <span>${escapeHtml(task.description || "没有描述")}</span>
            <div class="task-meta">
              <span class="pill">${statusLabels[task.status] || task.status}</span>
              <span class="pill">${priorityLabels[task.priority] || task.priority}</span>
              <span class="pill">估算 ${task.estimated_effort}</span>
              ${criteria}
            </div>
          </article>`;
        })
        .join("")
    : `<p class="empty">还没有任务。先确认计划，再拆解任务。</p>`;
}

function renderSnapshots() {
  const snapshots = (state.status?.snapshots || []).filter((item) => item.artifact === state.selectedArtifact);
  const select = $("#snapshotSelect");
  select.innerHTML = snapshots.length
    ? snapshots.map((item) => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)}</option>`).join("")
    : `<option value="">当前工件还没有快照</option>`;
  $("#rollbackHint").textContent = snapshots.length ? `可恢复 ${snapshots.length} 个历史版本。` : "保存工件后会自动出现快照。";
}

function renderEvents() {
  const events = state.status?.events || [];
  $("#eventList").innerHTML = events.length
    ? events
        .slice()
        .reverse()
        .map((event) => {
          const time = (event.timestamp || "").slice(0, 19).replace("T", " ");
          const label = eventLabels[event.event] || event.event || "未知记录";
          const detail = event.task_title || event.artifact || event.goal || "";
          return `<article class="event-item">
            <strong>${escapeHtml(label)}</strong>
            <span>${escapeHtml(detail)}</span>
            <small>${escapeHtml(time)}</small>
          </article>`;
        })
        .join("")
    : `<p class="empty">还没有历史记录。</p>`;
}

function renderModelSteps() {
  const settings = state.status?.llm_settings;
  if (!settings) return;
  const providers = settings.providers || [];
  const defaults = settings.provider_defaults || {};
  $("#modelSteps").innerHTML = (settings.steps || [])
    .map((step) => {
      const providerOptions = providers
        .map((provider) => `<option value="${provider.value}" ${provider.value === step.provider ? "selected" : ""}>${escapeHtml(provider.label)}</option>`)
        .join("");
      const inherited = step.inherits_default ? "继承默认" : "单独设置";
      const configured = step.configured ? "已可用" : "未填密钥或使用本地规则";
      return `<article class="model-step" data-step="${step.step}">
        <div class="model-step-title">
          <strong>${escapeHtml(step.label)}</strong>
          <span class="pill">${inherited} / ${configured}</span>
        </div>
        <div class="model-fields">
          <label>供应商
            <select class="model-provider">${providerOptions}</select>
          </label>
          <label>模型名称
            <input class="model-name" value="${escapeHtml(step.model || "")}" placeholder="例如 gpt-5.4" />
          </label>
          <label>API 地址
            <input class="model-base-url" value="${escapeHtml(step.base_url || "")}" placeholder="https://api.openai.com/v1" />
          </label>
          <label>API 密钥
            <input class="model-api-key" type="password" placeholder="${escapeHtml(step.masked_key || "留空则不修改")}" />
          </label>
        </div>
        <div class="model-actions">
          <button data-model-save="${step.step}">保存这一步模型</button>
          <button data-model-reset="${step.step}">恢复默认</button>
        </div>
      </article>`;
    })
    .join("");

  document.querySelectorAll(".model-provider").forEach((select) => {
    select.addEventListener("change", (event) => {
      const root = event.target.closest(".model-step");
      const provider = event.target.value;
      const stepDefaults = defaults[provider] || {};
      root.querySelector(".model-name").value = stepDefaults.model || "";
      root.querySelector(".model-base-url").value = stepDefaults.base_url || "";
    });
  });
}

function renderAutoStatus() {
  const auto = state.status?.auto_run || {};
  $("#autoStatus").textContent = auto.status || "还没有启动";
  $("#autoLog").innerHTML = (auto.events || [])
    .slice()
    .reverse()
    .map((item) => `<div><strong>${escapeHtml(item.message || "")}</strong><small>${escapeHtml((item.time || "").slice(0, 19).replace("T", " "))}</small></div>`)
    .join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function requestPayload() {
  return {
    goal: $("#goalInput").value.trim(),
    context: $("#contextInput").value.trim(),
  };
}

async function runAction(action) {
  const map = {
    discovery: ["/api/discovery", requestPayload()],
    spec: ["/api/spec", requestPayload()],
    approveSpec: ["/api/spec/approve", {}],
    plan: ["/api/plan", {}],
    approvePlan: ["/api/plan/approve", {}],
    tasks: ["/api/tasks", { replace: true }],
    execute: ["/api/execute", {}],
    executeSelected: ["/api/execute", { task_ids: selectedTaskIds() }],
    reviewPlan: ["/api/review/plan", {}],
    rollback: ["/api/artifact/rollback", { name: state.selectedArtifact, snapshot: $("#snapshotSelect").value }],
    autoRun: [
      "/api/auto-run",
      {
        goal: $("#goalInput").value.trim(),
        context: $("#contextInput").value.trim(),
        execute: $("#autoExecute").checked,
        max_cycles: Number($("#autoCycles").value || 50),
      },
    ],
  };
  const item = map[action];
  if (!item) return;
  if (action === "executeSelected" && item[1].task_ids.length === 0) {
    toast("请先选择至少一个待办任务");
    return;
  }
  setBusy(true);
  try {
    const result = await api(item[0], { method: "POST", body: JSON.stringify(item[1]) });
    if (action === "reviewPlan") {
      renderReview(result);
    }
    await refreshStatus();
    await loadArtifact(state.selectedArtifact);
    toast("操作完成");
  } catch (error) {
    toast(error.message);
  } finally {
    setBusy(false);
  }
}

function selectedTaskIds() {
  return [...document.querySelectorAll(".task-check:checked")].map((item) => Number(item.value));
}

function renderReview(result) {
  const target = $("#reviewResult");
  const issues = result.issues || [];
  target.innerHTML = issues.length
    ? `<strong>${escapeHtml(result.verdict)}</strong><ul>${issues.map((issue) => `<li>${escapeHtml(issue)}</li>`).join("")}</ul>`
    : `<strong>检查通过</strong><span>规格、计划和任务当前没有发现明显冲突。</span>`;
}

async function saveStepModel(stepName) {
  const root = document.querySelector(`.model-step[data-step="${stepName}"]`);
  if (!root) return;
  setBusy(true);
  try {
    await api("/api/llm-step", {
      method: "POST",
      body: JSON.stringify({
        step: stepName,
        provider: root.querySelector(".model-provider").value,
        model: root.querySelector(".model-name").value.trim(),
        base_url: root.querySelector(".model-base-url").value.trim(),
        api_key: root.querySelector(".model-api-key").value.trim(),
      }),
    });
    await refreshStatus();
    toast("这一步的模型设置已生效");
  } catch (error) {
    toast(error.message);
  } finally {
    setBusy(false);
  }
}

async function resetStepModel(stepName) {
  setBusy(true);
  try {
    await api("/api/llm-step", {
      method: "POST",
      body: JSON.stringify({ step: stepName, inherit_default: true }),
    });
    await refreshStatus();
    toast("已恢复默认模型");
  } catch (error) {
    toast(error.message);
  } finally {
    setBusy(false);
  }
}

async function saveCurrentArtifact() {
  setBusy(true);
  try {
    await api("/api/artifact", {
      method: "POST",
      body: JSON.stringify({
        name: state.selectedArtifact,
        content: $("#artifactEditor").value,
      }),
    });
    await refreshStatus();
    await loadArtifact(state.selectedArtifact);
    renderSnapshots();
    toast("已保存修改");
  } catch (error) {
    toast(error.message);
  } finally {
    setBusy(false);
  }
}

document.addEventListener("click", (event) => {
  const saveModel = event.target.closest("[data-model-save]");
  if (saveModel) {
    saveStepModel(saveModel.dataset.modelSave);
    return;
  }
  const resetModel = event.target.closest("[data-model-reset]");
  if (resetModel) {
    resetStepModel(resetModel.dataset.modelReset);
    return;
  }
  const actionButton = event.target.closest("[data-action]");
  if (actionButton) {
    runAction(actionButton.dataset.action);
    return;
  }
  const tab = event.target.closest("[data-artifact]");
  if (tab) {
    loadArtifact(tab.dataset.artifact)
      .then(renderSnapshots)
      .catch((error) => toast(error.message));
  }
});

$("#saveArtifact").addEventListener("click", saveCurrentArtifact);

async function boot() {
  try {
    await refreshStatus();
    await loadArtifact("discovery");
  } catch (error) {
    toast(error.message);
  }
}

boot();
