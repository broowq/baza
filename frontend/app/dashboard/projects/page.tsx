"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { FolderOpen } from "lucide-react";

import { api } from "@/lib/api";
import type { Project } from "@/lib/types";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api<Project[]>("/projects")
      .then(setProjects)
      .catch(() => {}) // silent — dashboard handles errors
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="mx-auto max-w-6xl px-6 py-8 lg:px-10">
      <div className="mb-6">
        <p className="text-[13px] text-gray-400 dark:text-gray-500">ОРГАНИЗАЦИЯ</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-[#191C1F] dark:text-white">Проекты</h1>
        <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
          Выберите проект, чтобы перейти к лидам, задачам и экспорту.
        </p>
      </div>

      {loading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-20 animate-pulse rounded-2xl bg-gray-100 dark:bg-[#1A1C1F]" />
          ))}
        </div>
      )}

      {!loading && projects.length === 0 && (
        <div className="rounded-2xl border border-dashed border-gray-200 bg-white py-16 text-center dark:border-[#2A2D31] dark:bg-[#1A1C1F]">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#F7F7F8] dark:bg-[#222527]">
            <FolderOpen className="text-gray-400" size={28} strokeWidth={1.5} />
          </div>
          <h2 className="text-[15px] font-semibold text-[#191C1F] dark:text-white">Проектов пока нет</h2>
          <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">Создайте проект на странице дашборда.</p>
          <Link
            href="/dashboard"
            className="mt-5 inline-flex items-center gap-1.5 rounded-full bg-[#191C1F] px-5 py-2.5 text-[13px] font-medium text-white transition-colors hover:bg-[#2A2D31] dark:bg-white dark:text-[#191C1F] dark:hover:bg-gray-100"
          >
            Перейти в дашборд
          </Link>
        </div>
      )}

      {!loading && projects.length > 0 && (
        <div className="space-y-3">
          {projects.map((project) => (
            <Link
              key={project.id}
              href={`/dashboard/projects/${project.id}`}
              className="flex items-center justify-between gap-4 rounded-2xl border border-gray-100 bg-white p-5 shadow-sm transition-all duration-200 hover:shadow-md dark:border-[#2A2D31] dark:bg-[#1A1C1F] dark:hover:border-[#3A3D41]"
            >
              <div>
                <h3 className="text-[15px] font-semibold text-[#191C1F] dark:text-white">{project.name}</h3>
                <p className="mt-1 text-[13px] text-gray-500 dark:text-gray-400">
                  {project.niche} · {project.geography} · {project.segments.join(", ") || "без сегментов"}
                </p>
              </div>
              <span className="shrink-0 rounded-full bg-[#F7F7F8] px-4 py-2 text-[13px] font-medium text-[#191C1F] transition-colors hover:bg-gray-200 dark:bg-[#222527] dark:text-white dark:hover:bg-[#2A2D31]">
                Открыть
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
