#if UNITY_EDITOR || DEVELOPMENT_BUILD
namespace Pathfinder.Dev
{
    // switchclean: a world-model switch closes every open UI, and measurements are fully world-model specific. In Play
    // (the backend's kitchen and Zabel gym: ServerConfig.SetOverride("http://127.0.0.1:8004") before Play):
    //   unity command eval --code 'return Pathfinder.Dev.AgentHarness.SwitchCloseCheck();'   then poll SwitchCloseResult()
    //   unity command eval --code 'return Pathfinder.Dev.AgentHarness.MeasureScopeCheck();'  then poll MeasureScopeResult()
    // (true: the same through Model view's wheel path, the gym on the table). Results are [Pathfinder.Check] switchclose.* /
    // measurescope.* lines. MeasureScopeCheck ends on the gym with the kitchen's items parked: the capture state.
    public static partial class AgentHarness
    {
        /// Everything that can be up at once, a real switch (all closed, logged); every main-slot card through the close
        /// run; the checkout kept through a switch while Pay is held, closed right after (nothing pays).
        public static string SwitchCloseCheck(bool modelView = false) => Pathfinder.Dev.SwitchCloseCheck.Run(modelView);

        public static string SwitchCloseResult() => Pathfinder.Dev.SwitchCloseCheck.Result();

        /// Every measurement kind drawn on the kitchen, the gym (World, or Model view), undo there, the kitchen again, the
        /// gym again: zero foreign renderers of each kind.
        public static string MeasureScopeCheck(bool modelView = false) => Pathfinder.Dev.MeasureScopeCheck.Run(modelView);

        public static string MeasureScopeResult() => Pathfinder.Dev.MeasureScopeCheck.Result();

        /// The last switch's close run: "Switched to <site>: closed [...]" (and what was kept).
        public static string LastSwitchClose() => $"{Pathfinder.SwitchClose.LastLine} (runs {Pathfinder.SwitchClose.Runs})";

        /// Close everything as a switch would, without switching (a probe; the log line names the site given).
        public static string CloseAllForSwitch(string site = "probe") => AppCommands.CloseAllForSwitch(site);
    }
}
#endif
