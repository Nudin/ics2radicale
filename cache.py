import json
import os
from typing import Any, Dict, Optional


class JSONCache:
    """Manage a cache of multiple key-value-pair stores saved in JSON files."""

    def __init__(self, appname: str):
        """
        Initialize the JSONCache instance.

        Parameters:
            appname (str): The name of the application == folder name
        """
        self.appname = appname
        self.cache_dir = self.get_cache_directory()
        self.projects: Dict[str, str] = {}
        self.data: Dict[str, Dict[str, Any]] = {}
        self.load_projects()

    def get_cache_directory(self) -> str:
        """
        Get the cache directory path.

        Returns:
            str: The path to the cache directory.
        """
        home_dir = os.path.expanduser("~")
        xdg_cache_home = os.environ.get(
            "XDG_CACHE_HOME", os.path.join(home_dir, ".cache")
        )
        cache_dir = os.path.join(xdg_cache_home, self.appname)
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        return cache_dir

    def load_projects(self) -> None:
        """Load existing projects from the cache directory."""
        for project_file in os.listdir(self.cache_dir):
            project_path = os.path.join(self.cache_dir, project_file)
            if os.path.isfile(project_path):
                project_name, _ = os.path.splitext(project_file)
                self.projects[project_name] = project_path
                self.load_cache(project_name)

    def load_cache(self, project_name: str):
        """
        Load the cache data for a specific project.

        Parameters:
            project_name (str): The name of the project.
        """
        project_file = self.projects.get(project_name)
        if project_file:
            try:
                with open(project_file, "r", encoding="utf-8") as file:
                    self.data[project_name] = json.load(file)
            except (FileNotFoundError, json.JSONDecodeError):
                self.data[project_name] = {}
        else:
            self.data[project_name] = {}

    def save_cache(self, project_name: str) -> None:
        """
        Save the cache data for a specific project.

        Parameters:
            project_name (str): The name of the project.
        """
        project_file = self.projects.get(project_name)
        if not project_file:
            project_file = os.path.join(self.cache_dir, f"{project_name}.json")
            self.projects[project_name] = project_file

        with open(project_file, "w", encoding="utf-8") as file:
            json.dump(self.data[project_name], file, ensure_ascii=False)

    def get(self, project_name: str, key: str, default: Optional[Any] = None) -> Any:
        """
        Get the value associated with a key from a specific project's cache.

        Parameters:
            project_name (str): The name of the project.
            key (str): The key to retrieve the value for.
            default: The default value to return if the key is not found. Defaults to None.

        Returns:
            Any: The value associated with the key, or the default value if the key is not found.
        """
        self.load_cache(project_name)
        return self.data[project_name].get(key, default)

    def set(self, project_name: str, key: str, value: Any) -> None:
        """
        Set a key-value pair in a specific project's cache.

        Parameters:
            project_name (str): The name of the project.
            key (str): The key to set the value for.
            value (Any): The value to store.
        """
        self.load_cache(project_name)
        self.data[project_name][key] = value
        self.save_cache(project_name)

    def delete(self, project_name: str, key: str) -> None:
        """
        Delete a key-value pair from a specific project's cache.

        Parameters:
            project_name (str): The name of the project.
            key (str): The key to delete.
        """
        self.load_cache(project_name)
        if key in self.data[project_name]:
            del self.data[project_name][key]
            self.save_cache(project_name)

    def clear(self, project_name: str) -> None:
        """
        Clear the entire cache for a specific project.

        Parameters:
            project_name (str): The name of the project.
        """
        project_file = self.projects.get(project_name)
        if project_file:
            os.remove(project_file)
            del self.projects[project_name]

    def get_subcache(self, project_name: str):
        """
        Get a subcache object that represents the cache for a specific project.

        Parameters:
            project_name (str): The name of the project.

        Returns:
            SubCache: The subcache object for the specified project.
        """

        class SubCache:
            def __init__(self, parent_cache: JSONCache, project_name: str):
                self.cache = parent_cache
                self.project_name = project_name

            def get(self, key: str, default: Optional[Any] = None) -> Any:
                return self.cache.get(self.project_name, key, default)

            def set(self, key: str, value: Any) -> None:
                self.cache.set(self.project_name, key, value)

            def delete(self, key: str) -> None:
                self.cache.delete(self.project_name, key)

            def clear(self) -> None:
                self.cache.clear(self.project_name)

        return SubCache(self, project_name)


if __name__ == "__main__":
    # Example usage:
    cache = JSONCache("my_app_name")

    # Set values for projects
    cache.set("project1", "key1", "value1")
    cache.set("project2", "key1", "value2")

    # Get a subcache for 'project1'
    p1_cache = cache.get_subcache("project1")
    value1 = p1_cache.get("key1")
    print(value1)  # Output: 'value1'
