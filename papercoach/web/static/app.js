const terminalStates = new Set(["succeeded", "failed"]);

const formatStatus = (status) => status.replace("-", " ");

const renderStatusCopy = (job) => {
  if (job.status === "queued") {
    return "Waiting for a worker to pick up the run.";
  }
  if (job.status === "running") {
    return job.progress?.message || "Extracting structure, generating selections, and rendering the annotated PDF.";
  }
  if (job.status === "failed") {
    return job.error || "The run failed.";
  }
  return "The annotated PDF is ready for viewing and download.";
};

const updateProgressPanel = (container, job) => {
  const progressPanel = container.querySelector("[data-progress-panel]");
  const progressStageCount = container.querySelector("[data-progress-stage-count]");
  const progressStageTitle = container.querySelector("[data-progress-stage-title]");
  const progressStageDetail = container.querySelector("[data-progress-stage-detail]");
  const progressCompleted = container.querySelector("[data-progress-completed]");
  const progressStarted = container.querySelector("[data-progress-started]");
  const progressFill = container.querySelector("[data-progress-fill]");
  const progressPercent = container.querySelector("[data-progress-percent]");
  if (!progressPanel) {
    return;
  }
  progressPanel.hidden = false;
  if (job.status === "running" && job.progress) {
    if (progressStageCount) {
      progressStageCount.textContent = `Stage ${job.progress.stage_index} of ${job.progress.total_stages}`;
    }
    if (progressStageTitle) {
      progressStageTitle.textContent = job.progress.stage_title;
    }
    if (progressStageDetail) {
      progressStageDetail.textContent = job.progress.stage_detail;
    }
    if (progressCompleted) {
      progressCompleted.textContent = `${job.progress.completed_steps}`;
    }
    if (progressStarted) {
      progressStarted.textContent = `${job.progress.started_steps}`;
    }
    if (progressFill) {
      progressFill.style.width = `${job.progress.progress_percent}%`;
    }
    if (progressPercent) {
      progressPercent.textContent = `${job.progress.progress_percent}%`;
    }
  } else if (job.status === "succeeded") {
    if (progressStageCount) {
      progressStageCount.textContent = "Pipeline complete";
    }
    if (progressStageTitle) {
      progressStageTitle.textContent = "Annotated PDF ready";
    }
    if (progressStageDetail) {
      progressStageDetail.textContent = "The run finished and the annotated PDF can now be opened.";
    }
    if (progressCompleted) {
      progressCompleted.textContent = job.progress ? `${job.progress.completed_steps}` : "0";
    }
    if (progressStarted) {
      progressStarted.textContent = job.progress ? `${job.progress.started_steps}` : "0";
    }
    if (progressFill) {
      progressFill.style.width = "100%";
    }
    if (progressPercent) {
      progressPercent.textContent = "100%";
    }
  } else if (job.status === "failed") {
    if (progressStageCount) {
      progressStageCount.textContent = "Pipeline stopped";
    }
    if (progressStageTitle) {
      progressStageTitle.textContent = "Run failed";
    }
    if (progressStageDetail) {
      progressStageDetail.textContent = job.error || "The pipeline stopped before the annotated PDF was ready.";
    }
    if (progressCompleted) {
      progressCompleted.textContent = job.progress ? `${job.progress.completed_steps}` : "0";
    }
    if (progressStarted) {
      progressStarted.textContent = job.progress ? `${job.progress.started_steps}` : "0";
    }
    if (progressFill) {
      progressFill.style.width = job.progress ? `${job.progress.progress_percent}%` : "0%";
    }
    if (progressPercent) {
      progressPercent.textContent = job.progress ? `${job.progress.progress_percent}%` : "0%";
    }
  } else {
    if (progressStageCount) {
      progressStageCount.textContent = "Preparing run";
    }
    if (progressStageTitle) {
      progressStageTitle.textContent = "Waiting to begin";
    }
    if (progressStageDetail) {
      progressStageDetail.textContent = "Waiting for the worker to start the first model step.";
    }
    if (progressCompleted) {
      progressCompleted.textContent = "0";
    }
    if (progressStarted) {
      progressStarted.textContent = "0";
    }
    if (progressFill) {
      progressFill.style.width = "0%";
    }
    if (progressPercent) {
      progressPercent.textContent = "0%";
    }
  }
};

const jobPage = document.querySelector("[data-job-page]");

if (jobPage) {
  const pollUrl = jobPage.getAttribute("data-poll-url");

  const updateDom = (job) => {
    const title = document.querySelector("[data-job-title]");
    const status = document.querySelector("[data-job-status]");
    const download = document.querySelector("[data-download-link]");
    const statusCopy = document.querySelector("[data-status-copy]");
    const shell = document.querySelector("[data-viewer-shell]");

    if (title && job.title) {
      title.textContent = job.title;
    }
    if (status) {
      status.textContent = formatStatus(job.status);
      status.className = `status-badge status-${job.status}`;
    }
    for (const key of ["highlights", "notes", "equations", "equation_notes"]) {
      const element = document.querySelector(`[data-count-${key.replace("_", "-")}]`);
      if (element) {
        element.textContent = `${job.counts[key]}`;
      }
    }
    if (statusCopy) {
      statusCopy.textContent = renderStatusCopy(job);
    }
    updateProgressPanel(document, job);

    if (download) {
      if (job.annotated_pdf_url) {
        download.href = job.annotated_pdf_url;
        download.removeAttribute("aria-disabled");
        download.classList.remove("is-disabled");
      } else {
        download.href = "#";
        download.setAttribute("aria-disabled", "true");
        download.classList.add("is-disabled");
      }
    }

    if (job.viewer_url && shell && !document.querySelector("[data-annotated-viewer]")) {
      shell.innerHTML = `<iframe src="${job.viewer_url}" title="Annotated PDF" data-annotated-viewer></iframe>`;
    }
  };

  const poll = async () => {
    const response = await fetch(pollUrl, { headers: { Accept: "application/json" } });
    if (!response.ok) {
      return;
    }
    const job = await response.json();
    updateDom(job);
    if (!terminalStates.has(job.status)) {
      window.setTimeout(poll, 1500);
    }
  };

  poll();
}

const uploadInput = document.querySelector("[data-upload-input]");

if (uploadInput) {
  const fileName = document.querySelector("[data-upload-filename]");

  const updateUploadName = () => {
    if (!fileName) {
      return;
    }
    const selected = uploadInput.files && uploadInput.files[0];
    fileName.textContent = selected ? selected.name : "No file selected yet";
  };

  uploadInput.addEventListener("change", updateUploadName);
  updateUploadName();
}
