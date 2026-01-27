# anibridge-provider-template

Two short provider implementations demonstrate how to implement the
[`anibridge_providers`](https://github.com/anibridge/anibridge-providers) SDK:

-   `ExampleLibraryProvider` in [`example_library.py`](./src/anibridge_example_provider/example_library.py)
-   `ExampleListProvider` in [`example_list.py`](./src/anibridge_example_provider/example_list.py)

```python
async def main() -> None:
    from anibridge_example_provider import ExampleLibraryProvider, ExampleListProvider

    library = ExampleLibraryProvider()
    list_provider = ExampleListProvider()

    await library.initialize()
    await list_provider.initialize()

    print("Library Sections:")
    sections = await library.get_sections()
    for section in sections:
        print(f"- {section.title} (key: {section.key})")

    print("\nLibrary Items:")
    for section in sections:
        items = await library.list_items(section)
        for item in items:
            print(f"- {item.title} (key: {item.key})")

"""
Library Sections:
- Demo Movies (key: movies)

Library Items:
- Castle in the Sky (key: castle-in-the-sky)
- Nausicaä of the Valley of the Wind (key: nausicaa)
"""
```

Use these classes as a starting point for your own provider implementations.
