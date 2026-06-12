package com.acme.orders;

import org.springframework.stereotype.Service;

@Service
public class ReportingService {
    private final ReportRepository reportRepository;

    public ReportingService(ReportRepository reportRepository) {
        this.reportRepository = reportRepository;
    }

    public java.util.List<Order> dailySummary(String since) {
        return reportRepository.findRecentWithCustomers(since);
    }
}
