export function Loader() {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
      <span className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-gray-200 border-t-[#191C1F] dark:border-gray-700 dark:border-t-white" />
      Загрузка...
    </div>
  );
}
