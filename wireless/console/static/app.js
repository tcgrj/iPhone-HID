const element = (id) => document.getElementById(id);
const task = element("task");
const notice = element("notice");
const manualButtons = [...document.querySelectorAll("[data-key]")];
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const defaultNotice = notice.textContent;
let token = "";
let lastEvent = -1;
let frameNumber = 0;
let imageUrl = "";

function say(text = defaultNotice, error = false) {
  notice.textContent = text;
  notice.classList.toggle("error", error);
}

function badge(id, text, good) {
  const item = element(id);
  item.replaceChildren(
    document.createElement("i"),
    document.createTextNode(text),
  );
  item.classList.toggle("good", good);
}

function renderEvents(events) {
  const id = events[0]?.id ?? 0;
  if (id === lastEvent) return;
  lastEvent = id;
  element("event-count").textContent = `${events.length} 条`;
  if (!events.length) return;
  const items = events.map((event) => {
    const row = document.createElement("li");
    row.dataset.kind = event.kind;
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    const detail = document.createElement("p");
    const time = document.createElement("time");
    title.textContent = event.title;
    detail.textContent = event.detail;
    time.textContent = event.time;
    copy.append(title, detail);
    row.append(document.createElement("i"), copy, time);
    return row;
  });
  element("timeline").replaceChildren(...items);
}

function renderState(state) {
  token = state.token;
  const { device, active, jobs } = state;
  badge(
    "screen-chip",
    device.live ? "手机画面已连接" : "等待手机投屏",
    device.live,
  );
  badge(
    "ble-chip",
    device.paired ? "iPhone 蓝牙已连接" : "等待 iPhone 蓝牙",
    device.paired,
  );
  badge("live-chip", device.live ? "实时" : "画面未更新", device.live);
  element("frame-meta").textContent = device.live
    ? `${device.fps.toFixed(1)} fps · ${state.planner?.provider === "ollama" ? "本地 " + state.planner.model : "AirPlay"}${device.command_ms == null ? "" : ` · 最近指令 ${Math.round(device.command_ms)} ms`}`
    : device.error || "等待新画面";
  element("frame-size").textContent = device.width
    ? `iPhone 屏幕 · ${device.width} × ${device.height}`
    : "iPhone 屏幕";
  // A still AirPlay screen is not a blank screen. Keep the last received frame.
  element("original").hidden = !imageUrl;
  element("screen").hidden = !imageUrl;
  element("screen-empty").hidden = Boolean(imageUrl);
  if (!device.live) {
    const age = device.age == null ? "连接中断" : `${Math.floor(device.age)} 秒未更新`;
    badge("live-chip", imageUrl ? `保留画面 · ${age}` : "等待投屏", false);
    element("frame-meta").textContent = imageUrl
      ? `${age} · 显示最后收到的画面，操作前将获取新帧`
      : device.error || "等待手机画面";
    if (!imageUrl) element("screen-empty").textContent = "等待手机投屏；收到画面后将持续显示。";
  }
  const queued = jobs.filter((job) => job.state === "queued").length;
  const busy = Boolean(active || queued);
  element("transport").textContent =
    device.transport === "wifi"
      ? "Mac → Wi-Fi → ESP32 → 蓝牙 → iPhone"
      : "等待开发板 Wi-Fi 连接";
  element("current").classList.toggle("busy", busy);
  element("run-state").classList.toggle("running", busy);
  element("run-state").textContent = active
    ? (active.phase === "waiting_screen" ? "等待画面" : "执行中")
    : queued
      ? "排队中"
      : ({blocked: "任务暂停", finish: "已完成", cancelled: "已停止"}[jobs[0]?.state] || "空闲");
  element("current-task").textContent =
    active?.task || jobs[0]?.task || "等待新任务";
  element("queue-label").textContent = active
    ? queued
      ? `${queued} 项等待执行`
      : (state.events[0]?.detail || "根据实时画面执行")
    : jobs[0]?.result || "提交后会在这里显示执行步骤";
  element("stop").disabled = !busy;
  element("submit").disabled = !state.model || !device.paired;
  manualButtons.forEach((button) => {
    button.disabled = busy || !device.paired || !device.live;
  });
  renderEvents(state.events);
}

async function updateState() {
  const response = await fetch("/api/state");
  if (!response.ok) throw new Error("本机服务暂时不可用");
  renderState(await response.json());
}

async function followState() {
  for (;;) {
    try {
      await updateState();
    } catch (error) {
      token = "";
      element("submit").disabled = true;
      element("stop").disabled = true;
      manualButtons.forEach((button) => {
        button.disabled = true;
      });
      badge("screen-chip", "本机服务离线", false);
      badge("live-chip", "离线", false);
      element("run-state").textContent = "服务连接中断";
      element("queue-label").textContent = "无法获取任务状态，请检查本机服务";
    }
    await sleep(750);
  }
}

async function followScreen() {
  for (;;) {
    try {
      const response = await fetch(`/api/frame?after=${frameNumber}`);
      if (response.status === 204) {
        if (response.headers.get("X-Camera-Restarted") === "1") frameNumber = 0;
        continue;
      }
      if (!response.ok) throw new Error("未收到画面");
      const previousUrl = imageUrl;
      imageUrl = URL.createObjectURL(await response.blob());
      frameNumber = Number(response.headers.get("X-Frame-Number"));
      const screen = element("screen");
      screen.src = imageUrl;
      screen.hidden = false;
      element("screen-empty").hidden = true;
      if (previousUrl) URL.revokeObjectURL(previousUrl);
    } catch (error) {
      await sleep(900);
    }
  }
}

async function post(path, data) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Console-Token": token },
    body: JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "操作未完成");
  await updateState();
  return result;
}

element("task-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const instruction = task.value.trim();
  if (!instruction) return;
  element("submit").disabled = true;
  try {
    const { id } = await post("/api/tasks", { task: instruction });
    task.value = "";
    say(`任务 #${id} 已加入队列。`);
  } catch (error) {
    say(error.message, true);
  }
});

task.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
    event.preventDefault();
    if (!element("submit").disabled) element("task-form").requestSubmit();
  }
});

element("stop").addEventListener("click", async () => {
  try {
    await post("/api/stop", {});
    say("已发出停止指令。");
  } catch (error) {
    say(error.message, true);
  }
});

document.querySelectorAll("[data-example]").forEach((button) => {
  button.addEventListener("click", () => {
    task.value = button.dataset.example;
    task.focus();
    say();
  });
});

manualButtons.forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      await post("/api/manual", { key: button.dataset.key });
      say();
    } catch (error) {
      say(error.message, true);
    }
  });
});

followState();
followScreen();

async function updateNetwork() {
  const response = await fetch("/api/network");
  if (!response.ok) throw new Error("无法读取网络状态");
  const state = await response.json();
  element("network-state").textContent = state.busy ? "配置中" : state.ip ? `${state.ssid} · ${state.ip}` : "未配置";
  element("network-notice").textContent = state.message;
  element("network-submit").disabled = state.busy || !token;
  element("network-refresh").disabled = state.busy || !token;
  if (state.ssid && !element("wifi-ssid").value && document.activeElement !== element("wifi-ssid")) {
    element("wifi-ssid").value = state.ssid;
  }
}

element("network-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const ssid = element("wifi-ssid").value;
  const password = element("wifi-password").value;
  element("network-submit").disabled = true;
  element("wifi-password").value = "";
  try {
    await post("/api/network", { ssid, password });
    await updateNetwork();
  } catch (error) {
    element("network-notice").textContent = error.message;
  }
});

element("network-refresh").addEventListener("click", async () => {
  try {
    await post("/api/network", { refresh: true });
    await updateNetwork();
  } catch (error) {
    element("network-notice").textContent = error.message;
  }
});

(async () => {
  for (;;) {
    await updateNetwork().catch(() => {});
    await sleep(1500);
  }
})();
