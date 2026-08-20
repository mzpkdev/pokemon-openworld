import { expect, test } from "@playwright/test";

test.describe("Map Atlas", () => {
  test("loads the application and regional map canvas", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Map atlas", exact: true })).toBeVisible();
    const atlas = page.locator("section[aria-label='Interactive map atlas']");
    await expect(atlas).toBeVisible();
    await expect(atlas.getByLabel("Interactive regional map")).toBeVisible();
    await expect(atlas.locator("canvas").first()).toBeVisible();
  });

  test("searches and inspects Littleroot Town's first non-rendered exit", async ({ page }) => {
    await page.goto("/");

    const search = page.getByRole("searchbox", { name: "Source name or map section" });
    await search.fill("MAPSEC_LITTLEROOT_TOWN");
    const searchResults = page.getByRole("list", { name: "Matching maps" });
    const littleroot = searchResults.getByRole("button", { name: /LittlerootTown/ });
    await expect(littleroot).toBeVisible();
    await littleroot.click();

    const details = page.locator("aside.map-details");
    await expect(details.getByRole("heading", { name: "LittlerootTown", exact: true })).toBeVisible();
    await expect.poll(() => new URL(page.url()).searchParams.get("region")).toBe("hoenn");
    await expect.poll(() => new URL(page.url()).searchParams.get("map")).toBe("LittlerootTown");

    await page.getByRole("checkbox", { name: "Exits" }).check();
    const exits = details.locator("ul.exit-list");
    await expect(exits).toBeVisible();
    const warpZero = exits.getByRole("button", { name: /^Warp 0/ });
    await warpZero.click();
    await expect(warpZero).toHaveAttribute("aria-pressed", "true");

    await expect(details.getByRole("heading", { name: "Warp 0 details", exact: true })).toBeVisible();
    await expect(details).toContainText("LittlerootTown_MaysHouse_1F");
    await expect(details).toContainText("The destination is not a rendered exterior map, so it cannot be focused here.");
  });
});
