package com.acme.orders;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

public interface ReportRepository extends JpaRepository<Order, Long> {
    @Query(value = "SELECT * FROM orders o JOIN customers c ON c.id = o.customer_id WHERE o.created_at > :since", nativeQuery = true)
    java.util.List<Order> findRecentWithCustomers(String since);
}
