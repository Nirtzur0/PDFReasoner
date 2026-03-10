const jobPage = document.querySelector("[data-job-page]");

if (jobPage) {
  const pollUrl = jobPage.getAttribute("data-poll-url");
  const terminalStates = new Set(["succeeded", "failed"]);

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
      status.textContent = job.status.replace("-", " ");
      status.className = `status-badge status-${job.status}`;
    }
    for (const key of ["highlights", "notes", "equations", "equation_notes"]) {
      const element = document.querySelector(`[data-count-${key.replace("_", "-")}]`);
      if (element) {
        element.textContent = `${job.counts[key]}`;
      }
    }
    if (job.status === "queued") {
      statusCopy.textContent = "Waiting for a worker to pick up the run.";
    } else if (job.status === "running") {
      statusCopy.textContent = "Extracting structure, generating selections, and rendering the annotated PDF.";
    } else if (job.status === "failed") {
      statusCopy.textContent = job.error || "The run failed.";
    } else {
      statusCopy.textContent = "The annotated PDF is ready for viewing and download.";
    }

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

    if (job.annotated_pdf_url && shell && !document.querySelector("[data-annotated-viewer]")) {
      shell.innerHTML = `<iframe src="${job.annotated_pdf_url}" title="Annotated PDF" data-annotated-viewer></iframe>`;
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
