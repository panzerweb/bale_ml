"""Plain-language notebook helpers, embedded by sync_panabo_notebook.py.

The embedded cell uses the notebook's pandas, numpy and configuration globals.
Keep these helpers independent of files so downloaded notebooks remain standalone.
"""


def method_label(method):
    return {"last_week": "Repeat last week's sales", "weekday_average": "Average of the last four matching weekdays",
            "random_forest": "Random Forest", "xgboost": "XGBoost", "lightgbm": "LightGBM"}.get(method, str(method))


def method_chart_label(method):
    return {"last_week":"Repeat last week", "weekday_average":"Four-week weekday average"}.get(method, method_label(method))


def category_label(category):
    if str(category) == ALL_CATEGORIES:
        return "All categories (mixed sale units)"
    labels = {str(k): str(v) for k, v in CATEGORY_LABELS.items()}
    return labels.get(str(category), f"Category {category} - name unavailable")


def readable_table(frame, labels=None):
    """Add display labels without changing the source table or exported schema."""
    result = frame.copy()
    if "category_id" in result:
        result.insert(result.columns.get_loc("category_id") + 1, "category_name", result.category_id.map(category_label))
    if "area_id" in result and labels:
        result.insert(result.columns.get_loc("area_id") + 1, "area_name", result.area_id.map(lambda a: labels.get(a, str(a))))
    if "method" in result:
        result["method"] = result.method.map(method_label)
    if "status" in result:
        meanings = {"eligible":"Ready to forecast", "insufficient_history":"Fewer than 56 completely reported dates",
                    "incomplete_reporting":"Some of the latest 28 dates have unknown sales",
                    "no_sales":"No recorded sales in the latest 28 dates",
                    "sparse_sales":"Fewer than seven sales-active dates in the latest 28 dates",
                    "new_group_or_changed_cohort_requires_retraining":"New combination or changed participating stores: retrain first",
                    "insufficient_store_evaluation":"Not enough comparable past tests for this store",
                    "saved_store_model_unavailable":"No saved store model was supplied"}
        result["status"] = result.status.map(lambda s: meanings.get(s, str(s).replace("_", " ")))
    if "predicted_units" in result:
        result["predicted_units"] = result.predicted_units.round(2)
    for column in ["lower_bound", "upper_bound"]:
        if column in result:
            result[column] = result[column].astype(object).where(result[column].notna(), "Unavailable")
    return result


def show_markdown(text):
    from IPython.display import Markdown, display
    display(Markdown(text))


METRIC_GUIDE = """How to read the scores (one prediction means one category in one area or store on one date):

- MAE: average number of units the daily estimate missed by. Lower is better; this chooses the method.
- RMSE: another error measure in units, giving larger misses more weight. Lower is better.
- bias: average prediction minus recorded sales. Negative means estimates tend to be too low; positive means too high. Closer to zero is better.
- WAPE_pct: total absolute error divided by total recorded sales, as a percentage. Lower is better. This is not percentage accuracy; unavailable when recorded sales total zero.
- rows: number of daily predictions checked, not the number of original sale lines.

These scores summarize past tests; they are not a guaranteed error range for a future prediction."""


def cleaning_explanation(audit):
    return (f"Read {audit['input_rows']:,} sale lines; kept {audit['accepted_completed_rows']:,} completed-sale lines. "
            f"Removed {audit['exact_duplicates_removed']:,} exact duplicates, excluded {audit['excluded_status_rows']:,} "
            f"lines with other sale statuses, and set aside {audit['quarantined_rows']:,} lines needing review. "
            + ("Unlocatable rejected records block the run until repaired." if audit['global_block'] else
               "No unlocatable rejected records block the whole run. Affected combinations may still be withheld."))


def validation_explanation(comparison):
    if comparison.empty:
        return "No comparable validation results are available; a best method cannot be declared."
    ordered = comparison.sort_values(["MAE", "tie_priority"] if "tie_priority" in comparison else ["MAE"], kind="stable")
    winner = ordered.iloc[0]
    rmse_best = comparison.loc[comparison.RMSE.eq(comparison.RMSE.min())]
    names = ", ".join(method_label(m) for m in rmse_best.method)
    text = (f"Validation choice: {method_label(winner.method)}. Its daily estimates missed by {winner.MAE:.2f} units on average (MAE). "
            f"Lowest RMSE: {names}, at {rmse_best.iloc[0].RMSE:.2f} units. ")
    if not rmse_best.method.eq(winner.method).any():
        text += "The measures favor different methods: MAE measures average absolute error; RMSE gives larger misses more weight. We choose by MAE, so you do not need to choose between the charts. "
    else:
        text += "The MAE choice also has the lowest RMSE. "
    if comparison.MAE.eq(winner.MAE).sum() > 1:
        text += "An exact MAE tie was resolved by the existing fixed method order (simple methods first). "
    text += "Selection uses full-precision scores; rounded displays can look tied. This choice covers all eligible combinations in this scope, not each category separately."
    return text


def evaluation_explanation(evaluation, method):
    if evaluation.get("mode") == "forecast_only":
        original = evaluation.get("training_evaluation", {})
        old = next((r for r in original.get("final", []) if r["method"] == method), None)
        detail = f" Its saved final-check MAE was {old['MAE']:.2f} units." if old else ""
        trained = evaluation.get("model_training_end")
        training_text = f" The saved model was trained using history through {trained}." if trained else ""
        return (f"Using the saved {method_label(method)} method to refresh the forecast. No new model comparison or accuracy measurement was performed."
                + training_text
                + detail + " Saved scores describe its earlier evaluation, not accuracy on the new forecast dates.")
    records = evaluation.get("validation", [])
    lines = [validation_explanation(pd.DataFrame(records))] if records else []
    selected = evaluation.get("validation_selected_method")
    baseline = evaluation.get("strongest_validation_baseline")
    final = {r["method"]: r for r in evaluation.get("final", [])}
    if method not in final:
        return "\n\n".join(lines + [evaluation.get("message", "No final-check results are available; no evaluated method can be recommended.")])
    lines.append(f"Method used for the forecast: {method_label(method)}. On the later final-check weeks, its daily estimates missed by {final[method]['MAE']:.2f} units on average.")
    measured = final[method]
    if measured.get("bias") is not None:
        bias = measured["bias"]
        lines.append(f"Its predictions averaged {abs(bias):.2f} units {'below' if bias < 0 else 'above'} recorded sales (signed bias {bias:+.2f}). This is an average tendency, not a correction to apply to every forecast.")
    if "WAPE_pct" in measured:
        wape = measured["WAPE_pct"]
        lines.append(f"Total absolute error was {wape:.2f}% of total recorded sales (WAPE); this is not an accuracy percentage." if wape is not None else
                     "WAPE is unavailable because the recorded sales total was zero.")
    if measured.get("rows") is not None:
        lines.append(f"These scores cover {measured['rows']:,} checked daily category predictions, not original sale lines.")
    if selected in final and baseline in final and selected != baseline:
        difference = final[baseline]["MAE"] - final[selected]["MAE"]
        base_error = final[baseline]["MAE"]
        percent = f" ({abs(difference) / base_error * 100:.1f}%)" if base_error > 0 else ""
        if method == baseline:
            lines.append(f"The selected model did not beat {method_label(baseline)} on final MAE, so the existing release rule used that simple method instead.")
        else:
            lines.append(f"Compared with {method_label(baseline)} (MAE {base_error:.2f}), the selected model reduced average error by {difference:.2f} units{percent}.")
    elif selected == baseline:
        lines.append("A simple method already won validation, so the final table has only that method; there is no need to compare it with itself.")
    lines.append("The later check compares only the validation choice and strongest simple method; the other candidates were screened in validation. This release choice uses these results, so it does not provide another independent test afterward. Best in this run does not establish that the error is acceptable for your business.")
    return "\n\n".join(lines)


FORECAST_GUIDE = """This table contains the estimates that will be exported for the next seven days.

- area_id / category_id: stable identifiers; the added names tell you which place and category they represent.
- forecast_date: the date being estimated. horizon_day: days ahead of the last historical date (1 = next day, 7 = seven days ahead).
- predicted_units: expected recorded sale units for that date and combination. A decimal is an estimate, not a fraction of an item you must sell.
- lower_bound / upper_bound: an estimated low-to-high range would appear here if supported. Unavailable means this version does not calculate a range; it does not mean zero uncertainty.
- unit_policy: one recorded sellable item/package counts as one unit. Different sizes are not converted to kg or mL.

An area estimate combines participating stores; it is not an instruction for one store to buy that quantity."""


def forecast_explanation(forecast, method, labels=None, store=False):
    if forecast.empty:
        return "No forecast was produced for this scope. Review the withheld statuses; missing forecasts do not mean zero sales."
    keys = STORE_GROUP if store else GROUP
    count = len(forecast[keys].drop_duplicates())
    row = forecast.iloc[0]
    place = (labels or {}).get(row.area_id, str(row.area_id))
    who = f"store {row.store_id} in {place}" if store else f"participating stores in {place}"
    return (f"Using {method_label(method)}, produced {len(forecast):,} daily estimates across {count:,} "
            f"{'store/category' if store else 'area/category'} combinations for {forecast.forecast_date.min().date()} "
            f"through {forecast.forecast_date.max().date()}. The displayed rows are a preview. "
            f"For example, {category_label(row.category_id)} for {who} on {row.forecast_date.date()} "
            f"has an estimate of {row.predicted_units:.2f}, or approximately {row.predicted_units:.0f} recorded units "
            f"({int(row.horizon_day)} day(s) after the historical cutoff). This is an expectation, not a guarantee or a calculated error range.")


def feature_label(name):
    raw = name.split("__", 1)[-1]
    fixed = {"day_of_week": "Day of the week", "day_of_month": "Day of the month",
             "month": "Month", "is_weekend": "Whether the date is a weekend", "lag_1":"Sales yesterday"}
    if raw in fixed:
        return fixed[raw]
    for prefix, text in [("lag_", "Sales {n} day(s) earlier"), ("mean_", "Average daily sales over the previous {n} days"),
                         ("std_", "Variation in daily sales over the previous {n} days")]:
        if raw.startswith(prefix):
            return text.format(n=raw[len(prefix):])
    if raw.startswith("category_id_"):
        return "Category identity: " + category_label(raw[len("category_id_"):])
    if raw.startswith("area_id_"):
        area = raw[len("area_id_"):]
        return "Area identity: " + globals().get("area_labels", {}).get(area, area)
    if raw.startswith("store_id_"):
        return "Store identity: " + raw[len("store_id_"):]
    return "Identity indicator: " + raw


def feature_usage(estimator, method):
    if estimator is None or not hasattr(estimator.named_steps["model"], "feature_importances_"):
        text = ("The selected simple method has no tree feature-usage scores. Its forecast follows the matching weekdays described above."
                if method in BASELINES else "Feature-usage scores are unavailable because there is no fitted tree model for this scope.")
        return pd.DataFrame(), text
    model = estimator.named_steps["model"]
    names = estimator.named_steps["preprocess"].get_feature_names_out()
    scores = pd.Series(model.feature_importances_, index=names).nlargest(12)
    split = method == "lightgbm" and model.importance_type == "split"
    meaning = ("Number of tree splits" if split else "Relative model importance")
    table = pd.DataFrame({"Input used by the model": [feature_label(n) for n in scores.index], meaning: scores.values})
    if split:
        explanation = "These values count how many tree splits used each input. A score of 267 means 267 splits, not 267 sales or 267 percent."
    elif method == "random_forest":
        explanation = "These relative scores summarize reductions in training error when trees split on an input. They are not sales quantities."
    else:
        explanation = "These relative scores summarize the model's gain from splits on an input. They are not sales quantities."
    explanation += " Scores are specific to this model and should not be compared across model types. Related inputs can share credit. They describe overall model usage, not why a particular forecast rose or fell, and do not prove a cause."
    if not table.empty:
        explanation += f" The highest-ranked input here is: {table.iloc[0, 0]}."
    return table, explanation


def daily_chart_takeaway(actual, future, cutoff):
    observed = actual.loc[actual.units.notna()]
    lines = []
    if not observed.empty:
        lines.append(f"Displayed recorded daily sales range from {observed.units.min():.1f} to {observed.units.max():.1f} units.")
    if future is not None and not future.empty:
        complete = len(future) == 7 and future.units.notna().all()
        if complete:
            total = float(future.units.sum())
            lines.append(f"The next-seven-day estimate totals {total:.1f} recorded units.")
            previous = actual.set_index("date").reindex(pd.date_range(cutoff-pd.Timedelta(days=6), cutoff))
            if previous.units.notna().all() and previous.units.sum() > 0:
                change = (total / previous.units.sum() - 1) * 100
                lines.append(f"That is {abs(change):.1f}% {'higher' if change >= 0 else 'lower'} than the previous complete week's recorded sales.")
        else:
            lines.append("A full seven-day total is unavailable because some forecasts are missing; missing is not zero.")
    lines.append("Use recurring peaks or changes to decide what to investigate in sales and reporting records. Check promotions, stock availability, and store participation before attributing a cause; the chart alone cannot identify it.")
    return " ".join(lines)


def describe_figure(fig, guide, takeaway):
    # Keep Figure return values compatible with PNG export and existing callers.
    fig._bale_guide, fig._bale_takeaway = guide, takeaway
    return fig


def show_guided_figure(fig):
    from IPython.display import display
    import matplotlib.pyplot as plt
    print("How to read this chart:", fig._bale_guide)
    display(fig)
    print("What this shows:", fig._bale_takeaway)
    plt.close(fig)


def scope_summary(title, evaluation, method):
    lines = [f"### {title}", evaluation_explanation(evaluation, method)]
    ranked = evaluation.get("validation", []) if evaluation.get("mode") != "forecast_only" else []
    if ranked:
        lines.append("Validation ranking by average daily error: " + "; ".join(
            f"{i+1}. {method_label(r['method'])}: {r['MAE']:.2f} units" for i, r in enumerate(sorted(ranked, key=lambda r: r['MAE']))))
    return "\n\n".join(lines)


def run_summary(transactions, observations, statuses, forecast, audit, evaluation, method, cutoff,
                data_kind, estimator, store_evaluation=None, store_method=None, labels=None):
    lines = ["## What this run tells you", "",
             f"The goal is to estimate recorded sales for the next seven days, { (cutoff+pd.Timedelta(days=1)).date()} through {(cutoff+pd.Timedelta(days=7)).date()}.",
             f"This run uses {data_kind.upper()} data: {len(transactions):,} accepted sale lines, "
             f"{transactions.store_id.nunique():,} stores, {observations.area_id.nunique():,} areas and "
             f"{observations.category_id.nunique():,} categories. Historical dates span {observations.date.min().date()} through {cutoff.date()}.",
             cleaning_explanation(audit),
             f"{int(statuses.status.eq('eligible').sum()):,} area/category combinations qualify; "
             f"{int(statuses.status.ne('eligible').sum()):,} are withheld. Missing reporting is kept unknown, not replaced by zero.",
             scope_summary("Area/category result", evaluation, method)]
    if globals().get("SMOKE_RUN", False):
        lines.insert(2, f"Verification smoke run using {MODEL_TREES} trees per learned model. These reduced settings are for checking execution, not the normal model comparison.")
    if store_evaluation is not None:
        lines.append(scope_summary("Individual-store result (evaluated separately)", store_evaluation, store_method))
        lines.append("Store forecasts are modeled separately and may not add up to the area forecast.")
    evidence = evaluation.get("training_evaluation", evaluation)
    windows = evidence.get("windows", {})
    for stage, title in [("validation", "Earlier model-comparison dates"), ("final", "Later final-check dates")]:
        dates = windows.get(stage, [])
        if dates:
            lines.append(f"{title}: {(pd.Timestamp(min(dates))+pd.Timedelta(days=1)).date()} through {(pd.Timestamp(max(dates))+pd.Timedelta(days=7)).date()} ({len(dates)} seven-day tests).")
    lines += ["### What the inputs tell the model",
              "The learned models use past sales (1, 7, 14 and 28 days earlier), recent 7/14/28-day averages and variation, calendar dates, and area/category identities; the store model also uses store identity. They do not receive promotions, weather, prices, or inventory levels as predictive inputs.",
              feature_usage(estimator, method)[1],
              "### How the dataset affects this result",
              "The first 28 dates provide the history needed to build inputs. Longer history allows more test weeks; this run uses the evaluation dates stated above. More rows do not automatically mean better forecasts. Incomplete reporting can exclude combinations. Recorded sales can be limited by stockouts, so these estimates do not measure all unmet demand. A recorded package counts as one unit regardless of its contents; category totals can mix sizes."]
    if data_kind == "synthetic":
        lines.append("These sales are generated examples. Their model ranking and error scores test this workflow; they do not establish real business accuracy or real customer behavior.")
    lines += ["### Forecast highlights", forecast_explanation(forecast, method, labels)]
    changes = []
    for key, g in forecast.groupby(GROUP):
        past = observations.loc[observations.area_id.eq(key[0]) & observations.category_id.eq(key[1]) &
                                observations.date.between(cutoff-pd.Timedelta(days=6), cutoff)]
        total = float(g.predicted_units.sum())
        if len(g) == 7 and len(past) == 7 and past.units_sold.notna().all() and past.units_sold.sum() > 0:
            changes.append((abs(total/past.units_sold.sum()-1), (labels or {}).get(key[0], key[0]), key[1], total,
                            (total/past.units_sold.sum()-1)*100))
    for _, place, category, total, change in sorted(changes, key=lambda r: r[0], reverse=True)[:3]:
        lines.append(f"- {place} / {category_label(category)}: {total:.1f} units expected over seven days, {change:+.1f}% versus the previous complete week. This is a forecasted change, not an observed future outcome or an explanation of its cause.")
    if not changes:
        lines.append("No complete positive previous-week comparison is available.")
    lines += ["### What to do with the result",
              "Review the forecast alongside your own stock and sales records. Investigate large changes and historical misses. No prediction range is calculated, and no business acceptance threshold has been declared. Use new real outcomes to check accuracy before relying on the result for decisions."]
    return "\n\n".join(lines) + "\n"
