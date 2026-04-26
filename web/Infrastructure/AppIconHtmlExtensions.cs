using Microsoft.AspNetCore.Html;
using Microsoft.AspNetCore.Mvc.Rendering;

namespace TimelineForAudio.Web.Infrastructure;

public static class AppIconHtmlExtensions
{
    public static IHtmlContent AppIcon(
        this IHtmlHelper html,
        string alias,
        string? className = null,
        bool decorative = true,
        string? title = null)
    {
        var icon = AppIconRegistry.Resolve(alias);
        var svg = new TagBuilder("svg");
        svg.AddCssClass("ui-icon");
        if (!string.IsNullOrWhiteSpace(className))
        {
            svg.AddCssClass(className);
        }

        svg.Attributes["focusable"] = "false";

        if (decorative || string.IsNullOrWhiteSpace(title))
        {
            svg.Attributes["aria-hidden"] = "true";
        }
        else
        {
            var titleId = $"icon-{Guid.NewGuid():N}";
            svg.Attributes["role"] = "img";
            svg.Attributes["aria-labelledby"] = titleId;

            var titleTag = new TagBuilder("title");
            titleTag.Attributes["id"] = titleId;
            titleTag.InnerHtml.Append(title);
            svg.InnerHtml.AppendHtml(titleTag);
        }

        var use = new TagBuilder("use");
        use.Attributes["href"] = $"{icon.SpritePath}#{icon.SymbolId}";
        svg.InnerHtml.AppendHtml(use);
        return svg;
    }
}
