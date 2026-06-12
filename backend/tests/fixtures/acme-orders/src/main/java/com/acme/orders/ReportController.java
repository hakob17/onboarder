package com.acme.orders;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/reports")
public class ReportController {
    private final ReportingService reportingService;

    public ReportController(ReportingService reportingService) {
        this.reportingService = reportingService;
    }

    @GetMapping("/daily")
    public java.util.List<Order> daily(@RequestParam String since) {
        return reportingService.dailySummary(since);
    }
}
