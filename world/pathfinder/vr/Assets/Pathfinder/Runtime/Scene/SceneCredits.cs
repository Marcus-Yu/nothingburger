namespace Pathfinder.Scene
{
    /// Attribution a scene package's source needs on screen while it's loaded (pure). The Matterport and Vexcel scenes
    /// need none today; add a site here when a source's licence asks for an on-screen credit.
    public static class SceneCredits
    {
        /// The credit for a loaded site, or null when it needs none.
        public static string For(string site) => null;
    }
}
